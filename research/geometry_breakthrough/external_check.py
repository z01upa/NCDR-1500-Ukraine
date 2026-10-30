from decoder import *
import urllib.request,urllib.parse
q='[out:json][timeout:25];(way(around:60,56.49471,9.97947)[highway];);out geom;'
u='https://overpass-api.de/api/interpreter?'+urllib.parse.urlencode({'data':q})
try:
 d=urllib.request.urlopen(u,timeout=40).read();(Path(__file__).parent/'evidence/osm_first.json').write_bytes(d); print(d[:500])
except Exception as e: print(type(e).__name__,str(e))
