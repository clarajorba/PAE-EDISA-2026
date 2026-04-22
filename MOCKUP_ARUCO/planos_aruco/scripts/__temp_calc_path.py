import json
import math

with open('flight_sequence.json', 'r', encoding='utf-8') as f:
    wps = json.load(f)

def dist(a, b):
    return math.dist(a['position'], b['position'])

lengths = [dist(wps[i - 1], wps[i]) for i in range(1, len(wps))]

total = sum(lengths)
print('total_distance', total)
print('waypoints', len(wps))
print('avg_segment', total / len(lengths))
print('first_7', lengths[:7])
print('transition E1-P6->E2-P0', lengths[6])
