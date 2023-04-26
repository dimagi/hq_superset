import logging
import ast
import os
import pandas as pd
import superset
import sqlalchemy

from contextlib import contextmanager
from datetime import datetime
from io import BytesIO
from zipfile import ZipFile
from sqlalchemy.dialects import postgresql
from flask import Response, abort, flash, g, redirect, request
from flask_appbuilder import expose
from flask_appbuilder.security.decorators import has_access, permission_name
from flask_login import current_user
from superset import db
from superset.connectors.sqla.models import SqlaTable
from superset.datasets.commands.delete import DeleteDatasetCommand
from superset.datasets.commands.exceptions import (
    DatasetDeleteFailedError,
    DatasetForbiddenError,
    DatasetNotFoundError,
)
from superset.models.core import Database
from superset.sql_parse import Table
from superset.views.base import BaseSupersetView
from superset.extensions import cache_manager

from .hq_domain import user_domains
from .oauth import get_valid_cchq_oauth_token
from .tasks import refresh_hq_datasource_task
from .utils import (
    get_column_dtypes,
    get_datasource_details_url,
    get_datasource_export_url,
    get_datasource_list_url,
    get_schema_name_for_domain,
    get_ucr_database,
    parse_date,
    AsyncImportHelper,
)

logger = logging.getLogger(__name__)


class HQDatasourceView(BaseSupersetView):

    def __init__(self):
        self.route_base = "/hq_datasource/"
        self.default_view = "list_hq_datasources"
        super().__init__()

    def _ucr_id_to_pks(self):
        tables = (
            db.session.query(SqlaTable)
            .filter_by(
                schema=get_schema_name_for_domain(g.hq_domain),
                database_id=get_ucr_database().id,
            )
        )
        return {
            table.table_name: table.id
            for table in tables.all()
        }

    @expose("/update/<datasource_id>", methods=["GET"])
    def create_or_update(self, datasource_id):
        # Fetches data for a datasource from HQ and creates/updates a superset table
        display_name = request.args.get("name")
        res = trigger_datasource_refresh(g.hq_domain, datasource_id, display_name)
        return res

    @expose("/list/", methods=["GET"])
    def list_hq_datasources(self):
        datasource_list_url = get_datasource_list_url(g.hq_domain)
        provider = superset.appbuilder.sm.oauth_remotes["commcare"]
        oauth_token = get_valid_cchq_oauth_token()
        response = provider.get(datasource_list_url, token=oauth_token)
        if response.status_code == 403:
            return Response(status=403)
        if response.status_code != 200:
            url = f"{provider.api_base_url}{datasource_list_url}"
            return Response(response=f"There was an error in fetching datasources from CommCareHQ at {url}", status=400)
        return self.render_template(
            "hq_datasource_list.html",
            hq_datasources=response.json(),
            ucr_id_to_pks=self._ucr_id_to_pks(),
            hq_base_url=provider.api_base_url
        )

    @expose("/delete/<datasource_pk>", methods=["GET"])
    def delete(self, datasource_pk):
        try:
            DeleteDatasetCommand(g.user, datasource_pk).run()
        except DatasetNotFoundError:
            return abort(404)
        except DatasetForbiddenError:
            return abort(403)
        except DatasetDeleteFailedError as ex:
            logger.error(
                "Error deleting model %s: %s",
                self.__class__.__name__,
                str(ex),
                exc_info=True,
            )
            return abort(description=str(ex))
        return redirect("/tablemodelview/list/")


class CCHQApiException(Exception):
    pass


def convert_to_array(string_array):
    """
    Converts the string representation of a list to a list.
    >>> convert_to_array("['hello', 'world']")
    ['hello', 'world']

    >>> convert_to_array("'hello', 'world'")
    ['hello', 'world']

    >>> convert_to_array("[None]")
    []

    >>> convert_to_array("hello, world")
    []
    """

    def array_is_falsy(array_values):
        return not array_values or array_values == [None]

    try:
        array_values = ast.literal_eval(string_array)
    except ValueError:
        return []

    if isinstance(array_values, tuple):
        array_values = list(array_values)

    # Test for corner cases
    if array_is_falsy(array_values):
        return []

    return array_values

# 10MB
ASYNC_DATASOURCE_IMPORT_LIMIT_IN_BYTES = 10000000

def trigger_datasource_refresh(domain, datasource_id, display_name):
    if AsyncImportHelper(domain, datasource_id).is_import_in_progress():
        flash("There is an active datasource import. "
              "Please wait for it to finish before before retrying")
        return redirect("/tablemodelview/list/")

    provider = superset.appbuilder.sm.oauth_remotes["commcare"]
    token = get_valid_cchq_oauth_token()
    path, size = download_datasource(provider, token, domain, datasource_id)
    datasource_defn = get_datasource_defn(provider, token, domain, datasource_id)
    if size < ASYNC_DATASOURCE_IMPORT_LIMIT_IN_BYTES:
        return refresh_hq_datasource(domain, datasource_id, display_name, path, datasource_defn)
    else:
        return queue_refresh_task(domain, datasource_id, display_name, path, datasource_defn)


def queue_refresh_task(domain, datasource_id, display_name, export_path, datasource_defn):
    task_id = refresh_hq_datasource_task.delay(domain, datasource_id, display_name, export_path, datasource_defn).task_id
    AsyncImportHelper(domain, datasource_id).mark_as_in_progress(task_id)
    flash("The datasource is being refreshed in the background as it is larger than 10MB. "
          "This may take a while, please wait for it to finish")
    return redirect("/tablemodelview/list/")


def refresh_hq_datasource(domain, datasource_id, display_name, file_path, datasource_defn):
    """
    Pulls the data from CommCare HQ and creates/replaces the
    corresponding Superset dataset
    """
    database = get_ucr_database()
    schema = get_schema_name_for_domain(domain)
    csv_table = Table(table=datasource_id, schema=schema)
    column_dtypes, date_columns, array_columns = get_column_dtypes(datasource_defn)

    converters = {column_name: convert_to_array for column_name in array_columns}
    # TODO: can we assume all array values will be of type TEXT?
    sqlconverters = {column_name: postgresql.ARRAY(sqlalchemy.types.TEXT) for column_name in array_columns}

    try:
        with get_datasource_file(file_path) as csv_file:
            df = pd.concat(
                pd.read_csv(
                    chunksize=1000,
                    filepath_or_buffer=csv_file,
                    encoding="utf-8",
                    parse_dates=date_columns,
                    date_parser=parse_date,
                    keep_default_na=True,
                    dtype=column_dtypes,
                    converters=converters,
                )
            )
        database.db_engine_spec.df_to_sql(
            database,
            csv_table,
            df,
            to_sql_kwargs={
                "chunksize": 1000,
                "if_exists": "replace",
                "dtype": sqlconverters,
            },
        )

        # Connect table to the database that should be used for exploration.
        # E.g. if hive was used to upload a csv, presto will be a better option
        # to explore the table.
        expore_database = database
        explore_database_id = database.explore_database_id
        if explore_database_id:
            expore_database = (
                    db.session.query(Database)
                    .filter_by(id=explore_database_id)
                    .one_or_none()
                    or database
            )

        sqla_table = (
            db.session.query(SqlaTable)
            .filter_by(
                table_name=datasource_id,
                schema=csv_table.schema,
                database_id=expore_database.id,
            )
            .one_or_none()
        )

        if sqla_table:
            sqla_table.description = display_name
            sqla_table.fetch_metadata()
        if not sqla_table:
            sqla_table = SqlaTable(table_name=datasource_id)
            # Store display name from HQ into description since
            #   sqla_table.table_name stores datasource_id
            sqla_table.description = display_name
            sqla_table.database = expore_database
            sqla_table.database_id = database.id
            sqla_table.user_id = g.user.get_id()
            sqla_table.schema = csv_table.schema
            sqla_table.fetch_metadata()
            db.session.add(sqla_table)
        db.session.commit()
    except Exception as ex:  # pylint: disable=broad-except
        db.session.rollback()
        raise ex

    os.remove(file_path)
    # superset.appbuilder.sm.add_permission_role(role, sqla_table.get_perm())
    return redirect("/tablemodelview/list/")


@contextmanager
def get_datasource_file(path):
    with ZipFile(path) as zipfile:
        filename = zipfile.namelist()[0]
        yield zipfile.open(filename)


def download_datasource(provider, oauth_token, domain, datasource_id):
    datasource_url = get_datasource_export_url(domain, datasource_id)
    response = provider.get(datasource_url, token=oauth_token)
    if response.status_code != 200:
        raise CCHQApiException("Error downloading the UCR export from HQ")

    filename = f"{datasource_id}_{datetime.now()}.zip"
    path = os.path.join(superset.config.SHARED_DIR, filename)
    with open(path, "wb") as f:
        f.write(response.content)

    return path, len(response.content)

def get_datasource_defn(provider, oauth_token, domain, datasource_id):
    url = get_datasource_details_url(domain, datasource_id)
    response = provider.get(url, token=oauth_token)
    if response.status_code != 200:
        raise CCHQApiException("Error downloading the UCR definition from HQ")
    return response.json()


class SelectDomainView(BaseSupersetView):
    """
    Select a Domain view, all roles that have 'profile' access on 'core.Superset' view can access this
    """
    # re-use core.Superset view's permission name
    class_permission_name = "Superset"

    def __init__(self):
        self.route_base = "/domain"
        self.default_view = "list"
        super().__init__()

    @expose('/list/', methods=['GET'])
    @has_access
    @permission_name("profile")
    def list(self):
        return self.render_template(
            'select_domain.html',
            next=request.args.get('next'),
            domains=user_domains(current_user)
        )

    @expose('/select/<hq_domain>/', methods=['GET'])
    @has_access
    @permission_name("profile")
    def select(self, hq_domain):
        response = redirect(request.args.get('next') or self.appbuilder.get_url_for_index)
        assert hq_domain in user_domains(current_user)
        response.set_cookie('hq_domain', hq_domain)
        superset.appbuilder.sm.sync_domain_role(hq_domain)
        return response
