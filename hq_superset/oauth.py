import logging
from flask import session
from superset.security import SupersetSecurityManager

class CommCareSecurityManager(SupersetSecurityManager):

    def oauth_user_info(self, provider, response=None):
        logging.debug("Oauth2 provider: {0}.".format(provider))
        if provider == 'commcare':
            logging.debug("Getting user info from {}".format(provider))
            user = self.appbuilder.sm.oauth_remotes[provider].get("api/v0.5/identity/", token=response).json()
            logging.debug("user - {}".format(user))
            return user

    def set_oauth_session(self, provider, oauth_response):
        super().set_oauth_session(provider, oauth_response)
        # The default FAB implementation only stores the access_token and disregards `refresh_token` and `expires_at`
        #   keep a track of refresh_token so that new access_token can be obtained
        session['oauth_response'] = oauth_response
