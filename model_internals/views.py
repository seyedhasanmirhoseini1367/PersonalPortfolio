from django.views.generic import ListView, DetailView
from .models import Walkthrough


class WalkthroughListView(ListView):
    model                = Walkthrough
    template_name        = 'model_internals/walkthrough_list.html'
    context_object_name  = 'walkthroughs'

    def get_queryset(self):
        return Walkthrough.objects.filter(is_published=True)


class WalkthroughDetailView(DetailView):
    model                = Walkthrough
    template_name        = 'model_internals/walkthrough_detail.html'
    context_object_name  = 'walkthrough'

    def get_queryset(self):
        return Walkthrough.objects.filter(is_published=True).prefetch_related('blocks', 'references')
