"""Views the project itself serves."""

from django.http import HttpRequest, JsonResponse


def healthz(request: HttpRequest) -> JsonResponse:
    """Report that the web process is up, without querying the database."""
    return JsonResponse({'status': 'ok'})
