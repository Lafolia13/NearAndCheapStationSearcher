import requests
from bs4 import BeautifulSoup
from retry import retry
import time
import pickle
from tqdm import tqdm
import os
import json
import re

RAPIDAPI_KEY = os.environ["RAPIDAPI_KEY"]
target_areas = ["tokyo", "chiba", "saitama", "kanagawa"]
target_stations = ["新宿", "東京", "渋谷", "品川"]
time_limit = 30 # 1 ~ 60
rent_limit = 13
output_top = 10
requests_per_minute = 30
output_warning = False

ignore_list = [
  "東京ディズニーランド",
  "リゾートゲートウェイ",
  "新綱島",
  "小川町",
  "霞ヶ関",
  "羽田空港第１・第２ターミナル"
]
'''
家賃情報が取れてない駅リスト:
  東京ディズニーランド
  リゾートゲートウェイ
  新綱島
駅名重複のため削除した駅リスト(他にもありそうだけど未確認):
  小川町
  霞ヶ関
微妙そうなので削除した駅リスト:
  羽田空港第１・第２ターミナル
'''

@retry(tries=3, delay=10, backoff=2)
def load_page(url):
  margin = requests_per_minute / 60

  html = requests.get(url)
  time.sleep(margin)
  soup = BeautifulSoup(html.content, "html.parser")
  return soup

def get_line_url(area):
  line_url = {}
  area_url = "https://suumo.jp/chintai/soba/{}/ensen/".format(area)
  soup = load_page(area_url)
  line_ul = soup.find_all(class_="searchitem-list")
  for ul in line_ul:
    li_items = ul.find_all("li")
    for li in li_items:
      a = li.find("a")
      if a != None:
        line = a.getText()
        url = a.get("href")
        line_url[line] = url
  return line_url

def get_station_rent(url):
  '''
  FR, ar, bs, ra, rn: 検索するときの隠しパラメータ
  sort: {1: 駅順, 2:家賃高い順, 3:家賃低い順}
  ts: {1: マンション, 2:アパート, 3:一戸建て・その他}
  mdKbn: {01: ワンルーム, 02: 1K/1DK, 03: 1LDK/2K/2DK, 04: 2LDK/3K/3DK, 05:3LDK/4K~}
  '''

  station_rent = {}
  line_url = "https://suumo.jp" + url
  soup = load_page(line_url)

  FR = soup.find(class_="ui-section-body").find("form").get("action")
  ar = soup.find(class_="ui-section-body").find("input", attrs={"name": "ar"}).get("value")
  bs = soup.find(class_="ui-section-body").find("input", attrs={"name": "bs"}).get("value")
  ra = soup.find(class_="ui-section-body").find("input", attrs={"name": "ra"}).get("value")
  rn = soup.find(class_="ui-section-body").find("input", attrs={"name": "rn"}).get("value")
  sort = "1"
  ts = "1"
  mdKbn = "03"
  rent_url = "https://suumo.jp{}?ar={}&bs={}&ra={}&rn={}&sort={}&ts={}&mdKbn={}".format(FR, ar, bs, ra, rn, sort, ts, mdKbn)

  soup = load_page(rent_url)
  table_list = soup.find_all(class_="js-graph-data")
  for table in table_list:
    td_list = table.find_all("td")
    a = td_list[0].find("a")
    if a != None:
      station = a.getText()
    else:
      station = td_list[0].getText()

    span = td_list[1].find(class_="graphpanel_matrix-td_graphinfo-strong")
    if span != None and td_list[3].find("a") != None:
      rent = float(span.getText())
    else:
      rent = 999

    station_rent[station] = rent

  return station_rent

def get_station_info():
  filename = "rent.pkl"
  if os.path.isfile(filename):
    with open(filename, "rb") as f:
      return pickle.load(f)

  station_info = {}

  for area in target_areas:
    line_list = get_line_url(area)
    for line, url in tqdm(line_list.items()):
      station_rent = get_station_rent(url)
      for station, rent in station_rent.items():
        if station not in station_info:
          station_info[station] = {
            "rent": rent,
            "lines": []
          }
        station_info[station]["lines"].append(line)

  for station in station_info:
    station_info[station]["lines"] = list(dict.fromkeys(station_info[station]["lines"]))

  with open(filename, "wb") as f:
    pickle.dump(station_info, f)

  return station_info

def get_node_id(station):
  url = "https://navitime-transport.p.rapidapi.com/transport_node/autocomplete"
  host = "navitime-transport.p.rapidapi.com"
  headers = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": host
  }
  params = {
    "word": station,
    "word_match": "prefix",
  }

  try:
    response = requests.request("GET", url, headers=headers, params=params)
    response.raise_for_status()
  except requests.exceptions.HTTPError as err:
    print(f'HTTPException occurred: {err}')
    return -1
  else:
    items = json.loads(response.text)["items"]
    for item in items:
      if re.match("^{}(\(東京都\)|\(埼玉県\)|\(千葉県\)|\(神奈川県\))?$".format(station), item["name"]):
        return item["id"]
    print("No perfect mutch was found with station: {}".format(station))
    return -1

def fix_fluctuation(station):
  if "（" in station:
    station = station[:station.index("（")]
  elif "〔" in station:
    station = station[:station.index("〔")]
  elif "[" in station:
    station = station[:station.index("[")]

  if station == "西ヶ原":
    return "西ケ原"
  elif station == "南阿佐ヶ谷":
    return "南阿佐ケ谷"
  elif station == "阿佐ヶ谷":
    return "阿佐ケ谷"
  elif station == "鶴ヶ峰":
    return "鶴ケ峰"
  elif station == "三ッ沢上町":
    return "三ツ沢上町"
  elif station == "千駄ヶ谷":
    return "千駄ケ谷"
  elif station == "保土ヶ谷":
    return "保土ケ谷"
  elif station == "市ヶ谷":
    return "市ケ谷"
  else:
    return station

def get_distance(node_id, start_station):
  url = "https://navitime-reachable.p.rapidapi.com/reachable_transit"
  host = "navitime-reachable.p.rapidapi.com"
  headers = {
    "x-rapidapi-key": RAPIDAPI_KEY,
    "x-rapidapi-host": host
  }
  params = {
    "term": 60,
    "start": node_id,
    "unuse": "domestic_flight.ferry.superexpress_train.sleeper_ultraexpress.shuttle_bus",
    "transit_limit": 30,
    "node_type": "station",
    "limit": 2000
  }

  try:
    response = requests.request("GET", url, headers=headers, params=params)
    response.raise_for_status()
  except requests.exceptions.HTTPError as err:
    print(f'HTTPException occurred: {err}')
    return {}
  else:
    items = json.loads(response.text)["items"]
    distance = {}
    for item in items:
      station = fix_fluctuation(item["name"])
      if station not in distance:
        distance[station] = {
          "time": int(item["time"]),
          "count": int(item["transit_count"]),
        }
      else:
        distance[station]["time"] = min(distance[station]["time"], int(item["time"]))
        distance[station]["count"] = min(distance[station]["count"], int(item["transit_count"]))

    distance[start_station] = {
      "time": 0,
      "count": 0
    }
    return distance

def get_distance_to_stations():
  basename = "distance.pkl"

  distance_list = {}
  for station in target_stations:
    filename = "{}-".format(station) + basename
    if os.path.isfile(filename):
      with open(filename, "rb") as f:
        distance_list[station] = pickle.load(f)
      continue

    node_id = get_node_id(station)
    if node_id == -1:
      continue
    distance = get_distance(node_id, station)
    distance_list[station] = distance

    with open(filename, "wb") as f:
      pickle.dump(distance, f)

  near_station_list = {}
  for _, distance in distance_list.items():
    if near_station_list == {}:
      near_station_list = set(distance.keys())
    else:
      near_station_list.intersection_update(set(distance.keys()))

  distance_to_stations = {}
  for station in near_station_list:
    distance_to_stations[station] = {}

  for start, distance in distance_list.items():
    for goal, time in distance.items():
      if goal in distance_to_stations:
        distance_to_stations[goal][start] = {
          "time": time["time"],
          "count": time["count"]
        }

  return distance_to_stations

def calculate_score(station_info, distance_to_stations):
  scores = []
  for station in distance_to_stations:
    station = fix_fluctuation(station)
    if station in ignore_list:
      continue
    elif station not in station_info:
      print("No such name station info: {}".format(station))
      continue
    else:
      if station_info[station]["rent"] > rent_limit:
        continue
      score = 0
      too_far = False
      for _, time in distance_to_stations[station].items():
        if time["time"] > time_limit:
          too_far = True
        score += time["time"] ** 2
      score *= station_info[station]["rent"] ** 2
      if not too_far:
        scores.append({
          "station": station,
          "score": score
        })
  
  scores = sorted(scores, key=lambda x: x["score"])
  cnt = 0
  for score in scores:
    station = score["station"]
    score = score["score"]
    print("駅名: {}, score: {}".format(station, int(score)))
    print("家賃相場: {} 万円".format(station_info[station]["rent"]))
    print("線路: ", end="")
    print(station_info[station]["lines"])
    print("到着時間: ")
    for start_station, time in distance_to_stations[station].items():
      print("\t{}: {}分, 乗り換え回数: {}".format(start_station, time["time"], time["count"]))
    print("")

    cnt += 1
    if cnt == output_top:
      break

if __name__ == "__main__":
  station_info = get_station_info()
  distance_to_stations = get_distance_to_stations()
  calculate_score(station_info, distance_to_stations)