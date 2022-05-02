import pandas as pd
import superset
from flask import url_for, render_template, redirect, request, session, g
from flask_appbuilder import expose, BaseView
from flask_appbuilder.security.decorators import has_access, permission_name
from flask_login import current_user
from io import BytesIO
from superset import db
from superset.connectors.sqla.models import SqlaTable
from superset.sql_parse import Table
from superset.models.core import Database
from zipfile import ZipFile
from .utils import get_datasource_export_url
from .oauth import get_valid_cchq_oauth_token


class HQDatasourceView(BaseView):

    def __init__(self):
        self.route_base = "/a/<domain>/datasource/"
        super().__init__()

    @expose("/update/<datasource_id>", methods=["POST"])
    def create_or_update(self, domain, datasource_id):
        # Fetches data for a datasource from HQ and creates/updates a superset table
        from .oauth import get_valid_cchq_oauth_token
        res = refresh_hq_datasource(domain, datasource_id)
        return res


class CCHQApiException(Exception):
    pass


def refresh_hq_datasource(domain, datasource_id):
    # This method pulls the data from CommCareHQ and creates/replaces the
    #   corresponding Superset dataset
    datasource_url = get_datasource_export_url(domain, datasource_id)
    provider = superset.appbuilder.sm.oauth_remotes["commcare"]
    oauth_token = get_valid_cchq_oauth_token()
    response = provider.get(datasource_url, token=oauth_token)
    if response.status_code != 200:
        # Todo; logging
        raise CCHQApiException("Error downloading the UCR export from HQ")
    zipfile = ZipFile(BytesIO(response.content))
    filename = zipfile.namelist()[0]
    # Upload to table
    database = get_ucr_database()
    schema = get_domain_db_schema(domain)
    csv_table = Table(table=datasource_id, schema=schema)

    try:
        df = pd.concat(
            pd.read_csv(
                chunksize=1000,
                filepath_or_buffer=zipfile.open(filename),
                encoding="utf-8",
                # Todo; make date parsing work
                parse_dates=True,
                infer_datetime_format=True,
                keep_default_na=True,
            )
        )

        database.db_engine_spec.df_to_sql(
            database,
            csv_table,
            df,
            to_sql_kwargs={
                "chunksize": 1000,
                "if_exists": "replace",
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
                table_name=csv_table.table,
                schema=csv_table.schema,
                database_id=expore_database.id,
            )
            .one_or_none()
        )

        if sqla_table:
            sqla_table.fetch_metadata()
        if not sqla_table:
            sqla_table = SqlaTable(table_name=csv_table.table)
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

    # Todo;
    # Assign the datasource:view access for the user's domain-role
    # Todo; could return the ID of the created datasource
    return "success"



def get_ucr_database():
    # Todo; get actual DB once that's implemented
    return db.session.query(Database).filter_by(database_name='HQ Data').one()


def get_domain_db_schema(domain):
    # Todo; get actual domain schema
    return 'public'
