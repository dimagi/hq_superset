class DatabaseMissing(Exception):
    pass


class HQAPIException(Exception):
    pass


class OAuthSessionExpired(Exception):
    pass


class UnitTestingOnly(Exception):
  pass
