CommCare HQ Superset Integration
================================

This is a Python package that integrates Superset and CommCare HQ.

Local Development
-----------------

### Preparing CommCare HQ

The 'User configurable reports UI' feature flag must be enabled for the
domain in CommCare HQ, even if the data sources to be imported were
created by Report Builder, not a UCR.


### Setting up a dev environment

While doing development on top of this integration, it's useful to
install this via `pip -e` option so that any changes made get reflected
directly without another `pip install`.

- Set up a virtual environment.
- Clone this repo and change into the directory of this repo.
- Run `cp superset_config.example.py superset_config.py` and override
  the config appropriately.
- Run `pip install -e .`

### CommCare HQ OAuth Integration

- Create an OAuth application on CommCare HQ using Django Admin at the URL
  `<hq_host>/admin/oauth2_provider/application/` with the following settings:

  - Redirect URIs: `<superset_host>/oauth-authorized/commcare`

  - Leave "Post logout redirect URIs" empty.

  - Client type: Confidential

  - Authorization grant type: Authorization code

  - Give your OAuth application a name that users would recognize,
    like "CommCare Analytics" or "HQ Superset". This name will appear
    in CommCare HQ's dialog box requesting authorization from the
    user.

  - Leave "Skip authorization" unchecked

  - Algorithm: No OIDC support

- Update `OAUTH_PROVIDERS` setting in `superset_config.py` with OAuth
  client credentials obtained from HQ.


### Initialize Superset

Read through the initialization instructions at
https://superset.apache.org/docs/installation/installing-superset-from-scratch/#installing-and-initializing-superset.

Create a database for Superset, and a database for storing data from
CommCare HQ. Adapt the username and database names to suit your
environment.
```bash
$ createdb -h localhost -p 5432 -U postgres superset
$ createdb -h localhost -p 5432 -U postgres superset_hq_data
```

Set the following environment variables:
```bash
$ export FLASK_APP=superset
$ export SUPERSET_CONFIG_PATH=/path/to/superset_config.py
```

Initialize the database. Create an administrator. Create default roles
and permissions:
```bash
$ superset db upgrade
$ superset fab create-admin
$ superset load_examples  # (Optional)
$ superset init
```
You may skip `superset load_examples`, although they could be useful.

You should now be able to run superset using the `superset run` command:
```bash
$ superset run -p 8088 --with-threads --reload --debugger
```

You can now log in as a CommCare HQ web user.


### Importing UCRs using Redis and Celery


Celery is used to import UCRs that are larger than
`hq_superset.views.ASYNC_DATASOURCE_IMPORT_LIMIT_IN_BYTES`. If you need
to import UCRs larger than this, you need to run Celery to import them.
Here is how celery can be run locally.

- Install and run Redis
- Add Redis and Celery config sections from
  `superset_config.example.py` to your local `superset_config.py`.
- Run
  `celery --app=superset.tasks.celery_app:app worker --pool=prefork -O fair -c 4`
  in the Superset virtualenv.


### Testing

Tests use pytest, which is included in `requirements_dev.txt`:

    $ pip install -r requirements_test.txt
    $ pytest

The test runner can only run tests that do not import from Superset. The
code you want to test will need to be in a module whose dependencies
don't include Superset.


Upgrading Superset
------------------

`dimagi-superset` is a requirement of this `hq_superset` package. It is
a fork of `apache-superset`, and adds important features to it,
necessary for `hq_superset`. For more information about how to upgrade
`dimagi-superset`, see [Dimagi Superset Fork](apache-superset.md).
