
def patch_superset_config(config):
    from . import oauth

    config.FLASK_APP_MUTATOR = flask_app_mutator
    config.CUSTOM_SECURITY_MANAGER = oauth.CommCareSecurityManager

def flask_app_mutator(app):
    # Import the views (which assumes the app is initialized) here
    # return
    from . import hq_domain
    from . import views
    from superset.extensions import appbuilder
    appbuilder.add_view(views.SelectDomainView, 'Select Domain')
    app.before_request_funcs.setdefault(None, []).append(
        hq_domain.before_request_hook
    )
    app.strict_slashes = False
