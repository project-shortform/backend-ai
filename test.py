import requests
import time

API_TOKEN = "__pltZwexKkh5z8ScmWcG9hPLenuDyUBKgrJJbfv3dY5R"

HEADERS = {'Authorization': f'Bearer {API_TOKEN}'}

# get my actor
r = requests.get('https://typecast.ai/api/actor', headers=HEADERS)
my_actors = r.json()['result']
my_first_actor = my_actors[0]
my_first_actor_id = my_first_actor['actor_id']

from pprint import pprint

pprint(my_actors)

