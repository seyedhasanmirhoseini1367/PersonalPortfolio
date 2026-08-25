from django.views.generic import ListView, DetailView
from .models import Walkthrough


class WalkthroughListView(ListView):
    model                = Walkthrough
    template_name        = 'model_internals/walkthrough_list.html'
    context_object_name  = 'walkthroughs'

    def get_queryset(self):
        return Walkthrough.objects.filter(is_published=True)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Group for display, keeping CATEGORY_CHOICES order (which is the
        # intended reading order) and dropping any group with no walkthroughs.
        by_cat = {}
        for w in ctx['walkthroughs']:
            by_cat.setdefault(w.category, []).append(w)
        ctx['groups'] = [
            {'code': code, 'label': label,
             'blurb': Walkthrough.CATEGORY_BLURBS.get(code, ''),
             'items': by_cat[code]}
            for code, label in Walkthrough.CATEGORY_CHOICES if code in by_cat
        ]
        ctx['total'] = len(ctx['walkthroughs'])
        return ctx


class WalkthroughDetailView(DetailView):
    model                = Walkthrough
    template_name        = 'model_internals/walkthrough_detail.html'
    context_object_name  = 'walkthrough'

    def get_queryset(self):
        return Walkthrough.objects.filter(is_published=True).prefetch_related('blocks', 'references')
