from rest_framework.throttling import AnonRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    scope = "login"


class PasswordResetRateThrottle(AnonRateThrottle):
    scope = "password_reset"


class AcceptInviteRateThrottle(AnonRateThrottle):
    scope = "accept_invite"
