"""Site-wide middleware."""
from django.conf import settings
from django.http import HttpResponsePermanentRedirect


class StripWwwMiddleware:
    """Send www.example.com to example.com, keeping the path and query.

    Browsers keep sign-in cookies per host, so a site answering on both addresses has two separate sign-ins:
    someone signed in on www. looks signed out on the bare domain. One address means one sign-in.
    GET and HEAD get a 301; anything else a 308, which keeps the method and body (a form post stays a post).
    Only redirects when the bare domain is itself an allowed host, so nothing changes where it is not served.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(settings, 'STRIP_WWW', True):
            host = request.get_host()
            if host.lower().startswith('www.'):
                bare = host[4:]
                hostname = bare.split(':')[0].lower()
                allowed = [h.lower() for h in settings.ALLOWED_HOSTS]
                if hostname in allowed or '.' + hostname in allowed or '*' in allowed:
                    url = f'{request.scheme}://{bare}{request.get_full_path()}'
                    if request.method in ('GET', 'HEAD'):
                        return HttpResponsePermanentRedirect(url)
                    response = HttpResponsePermanentRedirect(url)
                    response.status_code = 308
                    return response
        return self.get_response(request)
