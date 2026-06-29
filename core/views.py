from django.shortcuts import render


def home(request):
    """
    Coming Soon homepage. Renders brand-aware copy from request.brand.

    Marketing / product copy lands in Sprint 5; this view is intentionally
    minimal so it's stable across Sprints 1-4 while the platform fills in.
    """
    return render(request, 'home.html')
