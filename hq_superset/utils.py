import ast
from contextlib import contextmanager
from datetime import date, datetime
from zipfile import ZipFile

import pandas
import sqlalchemy
from cryptography.fernet import Fernet
from flask import current_app
from flask_login import current_user
from superset.utils.database import get_or_create_db

from .const import HQ_DATA

DOMAIN_PREFIX = "hqdomain_"
SESSION_USER_DOMAINS_KEY = "user_hq_domains"
SESSION_OAUTH_RESPONSE_KEY = "oauth_response"


class CCHQApiException(Exception):
    pass


def get_hq_database():
    db_uri = current_app.config['SQLALCHEMY_BINDS'][HQ_DATA]
    return get_or_create_db(HQ_DATA, db_uri)


def get_schema_name_for_domain(domain):
    # Prefix in-case domain name matches with know schemas such as public
    return f"{DOMAIN_PREFIX}{domain}"


def get_role_name_for_domain(domain):
    # Prefix in-case domain name matches with known role names such as admin
    # Same prefix pattern as schema only by coincidence, not a must.
    return f"{DOMAIN_PREFIX}{domain}"


def get_column_dtypes(datasource_defn):
    """
    Maps UCR column data types to Pandas data types.

    See corehq/apps/userreports/datatypes.py for possible data types.
    """
    # TODO: How are array indicators handled in CSV export?
    pandas_dtypes = {
        'date': 'datetime64[ns]',
        'datetime': 'datetime64[ns]',
        'string': 'string',
        'integer': 'Int64',
        'decimal': 'Float64',
        'small_integer': 'Int8',  # TODO: Is this true?
    }
    column_dtypes = {'doc_id': 'string'}
    date_columns = ['inserted_at']
    array_type_columns = []
    for ind in datasource_defn['configured_indicators']:
        indicator_datatype = ind.get('datatype', 'string')

        if indicator_datatype == "array":
            array_type_columns.append(ind['column_id'])
        elif pandas_dtypes[indicator_datatype] == 'datetime64[ns]':
            # the dtype datetime64[ns] is not supported for parsing,
            # pass this column using parse_dates instead
            date_columns.append(ind['column_id'])
        else:
            column_dtypes[ind['column_id']] = pandas_dtypes[indicator_datatype]
    return column_dtypes, date_columns, array_type_columns


def parse_date(date_str):
    """
    Simple, fast date parser for dates formatted by CommCare HQ.

    >>> parse_date('2022-02-24 12:29:19.450137')
    datetime.datetime(2022, 2, 24, 12, 29, 19, 450137)
    >>> parse_date('2022-02-22')
    datetime.date(2022, 2, 22)
    >>> parse_date('not a date')
    'not a date'

    """
    if pandas.isna(date_str):
        # data is missing/None
        return None
    try:
        if len(date_str) > 10:
            return datetime.fromisoformat(date_str)
        else:
            return date.fromisoformat(date_str)
    except ValueError:
        return date_str


class DomainSyncUtil:

    def __init__(self, security_manager):
        self.sm = security_manager

    def _ensure_domain_role_created(self, domain):
        # This inbuilt method creates only if the role doesn't exist.
        return self.sm.add_role(get_role_name_for_domain(domain))

    def _ensure_schema_perm_created(self, domain):
        menu_name = self.sm.get_schema_perm(get_hq_database(), get_schema_name_for_domain(domain))
        permission = self.sm.find_permission_view_menu("schema_access", menu_name)
        if not permission:
            permission = self.sm.add_permission_view_menu("schema_access", menu_name)
        return permission

    @staticmethod
    def _ensure_schema_created(domain):
        schema_name = get_schema_name_for_domain(domain)
        database = get_hq_database()
        with database.get_sqla_engine_with_context() as engine:
            if not engine.dialect.has_schema(engine, schema_name):
                engine.execute(sqlalchemy.schema.CreateSchema(schema_name))

    def re_eval_roles(self, existing_roles, new_domain_role):
        # Filter out other domain roles
        new_domain_roles = [
            r
            for r in existing_roles
            if not r.name.startswith(DOMAIN_PREFIX)
        ] + [new_domain_role]
        additional_roles = [
            self.sm.add_role(r)
            for r in self.sm.appbuilder.app.config['AUTH_USER_ADDITIONAL_ROLES']
        ]
        return new_domain_roles + additional_roles

    def sync_domain_role(self, domain):
        # This creates DB schema, role and schema permissions for the domain and
        #   assigns the role to the current_user
        self._ensure_schema_created(domain)
        permission = self._ensure_schema_perm_created(domain)
        role = self._ensure_domain_role_created(domain)
        self.sm.add_permission_role(role, permission)
        current_user.roles = self.re_eval_roles(current_user.roles, role)
        self.sm.get_session.add(current_user)
        self.sm.get_session.commit()


@contextmanager
def get_datasource_file(path):
    with ZipFile(path) as zipfile:
        filename = zipfile.namelist()[0]
        yield zipfile.open(filename)


def get_fernet_keys():
    return [
        Fernet(encoded(key, 'ascii'))
        for key in current_app.config['FERNET_KEYS']
    ]


def encoded(string_maybe, encoding):
    """
    Returns ``string_maybe`` encoded with ``encoding``, otherwise
    returns it unchanged.

    >>> encoded('abc', 'utf-8')
    b'abc'
    >>> encoded(b'abc', 'ascii')
    b'abc'
    >>> encoded(123, 'utf-8')
    123

    """
    if hasattr(string_maybe, 'encode'):
        return string_maybe.encode(encoding)
    return string_maybe


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


def get_explore_database(database):
    """
    Returns the database that should be used for exploration. e.g. If
    Hive was used to upload a CSV, Presto will be a better option to
    explore its tables.
    """
    from superset import db
    from superset.models.core import Database

    explore_database_id = database.explore_database_id
    if explore_database_id:
        return (
            db.session.query(Database)
            .filter_by(id=explore_database_id)
            .one_or_none()
            or database
        )
    else:
        return database
