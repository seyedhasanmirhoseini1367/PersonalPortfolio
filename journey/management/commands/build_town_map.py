from django.conf import settings
from django.core.management.base import BaseCommand

from journey import town_map


class Command(BaseCommand):
    help = 'Write the LearningJourney town map (a Tiled JSON map) to static/journey/town/town.json.'

    def handle(self, *args, **options):
        path = settings.BASE_DIR / 'static' / 'journey' / 'town' / 'town.json'
        data = town_map.write(path)
        town_map.render_preview(path.with_name('preview.png'), path.with_name('tiles.png'))
        self.stdout.write(f'Wrote {path} ({data["width"]} x {data["height"]} tiles, {len(data["layers"][-1]["objects"])} objects).')
