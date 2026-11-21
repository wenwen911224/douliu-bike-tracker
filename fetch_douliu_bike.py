from datetime import datetime, timezone, timedelta
import os
import re
import pandas as pd
import requests

# TDX OAuth 2.0 Token 端點與雲林縣公共自行車端點（含 /City/ 路徑）
TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
STATION_URL = "https://tdx.transportdata.tw/api/basic/v2/Bike/Station/City/YunlinCounty?$format=JSON"
AVAILABILITY_URL = "https://tdx.transportdata.tw/api/basic/v2/Bike/Availability/City/YunlinCounty?$format=JSON"

# 斗六市目標站點名稱清單
DOULIU_STATION_NAMES = [
    "斗六棒球場",
    "斗六國中",
    "斗六國小",
    "斗六水岸公園",
    "雲林科技大學",
    "雲林縣體育場",
    "中山紀念公園",
    "行啟紀念館",
    "雲林縣政府",
    "南聖宮",
    "鎮西國小",
    "公誠公園",
    "斗六民生公園",
    "斗六高中",
    "成大醫院",
    "斗六家商",
    "斗六家樂福",
    "雲林科技大學(龍潭路)",
    "斗六火車站前站",
    "斗六火車站後站",
    "龍潭社區活動中心",
    "雲林溪美食廣場",
    "水資源二號公園",
    "雲林縣警察局斗六分局",
    "斗六觀光夜市",
    "嘉東里",
    "勞工育樂中心",
    "石榴車站",
    "福天吊橋",
    "咬狗籃球場",
    "石榴國中",
    "石榴國小",
    "長和宮",
    "崙峰里",
    "久安里(三殿宮)",
    "正心中學",
    "經濟部斗六產業園區服務中心",
    "古坑綠色隧道公園",
    "雲林國中",
    "鎮南國小",
    "斗六大智公園",
    "波麗士公園",
    "菜公莊",
    "斗六承天宮",
    "斗六鎮東公園",
    "斗六文德公園",
    "斗六永樂公園",
    "斗六消防局第一大隊斗六消防分局",
    "明德里社區多功能活動中心",
    "萬年莊",
    "中南里",
    "十三里社區多功能活動中心",
    "榴中福德宮",
    "德安社區",
    "福興路",
    "斗六德龍宮",
    "南京西路",
    "明德北路與保源六街路口",
    "斗六保清宮",
    "保長國小",
    "斗六進天宮",
    "龍潭鄰里公園",
    "長安派出所",
    "長平里",
    "虎溪豐泰",
    "虎尾溪福龍宮",
    "崙仔集會所",
    "保竹李天宮",
    "保長路",
    "九老爺(久安南路)",
    "江厝路",
    "瓦厝玄安宮",
    "頂柴福德宮",
    "東市場停車場",
    "溝壩里",
    "雲林縣政府(文化觀光處)",
    "福懋二廠",
    "福懋一廠",
    "斗六名門",
    "斗六家商(擴站)",
    "棒球場停車場",
    "福德街停車場",
    "湖山里(玉當山廟前)",
    "公誠國小",
    "明德北路一段",
    "溪州里",
    "三公園區",
    "璞樸莊園",
    "十三里(聖德宮)",
    "十三里(頂水尾口福德宮)",
    "十三里(武德宮)",
    "警察局斗六分局(台1丁)",
    "成功里(台3線)",
    "斗六玄太宮(將爺廟)",
    "寧濟御庭",
    "石榴班振王宮",
    "榴南公園",
    "林頭北天宮",
]


def normalize_station_name(name) -> str:
    """清理站點名稱空白與全半形括號，避免因符號或空白差異漏抓"""
    if not isinstance(name, str) or not pd.notna(name):
        return ""
    cleaned = name.strip()
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    cleaned = re.sub(r"\s+", "", cleaned)
    return cleaned


def get_tdx_token(client_id: str, client_secret: str) -> str:
    """使用 Client ID 與 Client Secret 向 TDX 取得 Access Token"""
    headers = {"content-type": "application/x-www-form-urlencoded"}
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    response = requests.post(TOKEN_URL, headers=headers, data=payload, timeout=30)
    response.raise_for_status()
    return response.json()["access_token"]


def fetch_json(url: str, access_token: str) -> list[dict]:
    """攜帶 Bearer Token 呼叫 TDX API 並回傳 JSON 資料"""
    headers = {
        "authorization": f"Bearer {access_token}",
        "Accept-Encoding": "gzip",
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def build_douliu_bike_df(stations_raw: list[dict], avail_raw: list[dict], fetched_at: str) -> pd.DataFrame:
    """依斗六市站點名稱清單篩選站點，合併即時車況並加上時間戳記"""
    df_stations = pd.DataFrame(stations_raw)
    df_avail = pd.DataFrame(avail_raw)

    print(f"雲林縣 Station 原始筆數：{len(df_stations)}，Availability 原始筆數：{len(df_avail)}")

    # 解析站點名稱
    if "StationName" in df_stations.columns:
        df_stations["station_name"] = df_stations["StationName"].apply(
            lambda x: x.get("Zh_tw") if isinstance(x, dict) and pd.notna(x.get("Zh_tw")) else None
        )
    else:
        df_stations["station_name"] = None

    # 解析站點地址／位置（若無中文地址則改用經緯度座標）
    if "StationAddress" in df_stations.columns:
        df_stations["address"] = df_stations["StationAddress"].apply(
            lambda x: x.get("Zh_tw") if isinstance(x, dict) and pd.notna(x.get("Zh_tw")) else None
        )
    else:
        df_stations["address"] = None

    def extract_coords(row):
        pos = row.get("StationPosition")
        if isinstance(pos, dict):
            lat = pos.get("PositionLat")
            lon = pos.get("PositionLon")
            if pd.notna(lat) and pd.notna(lon):
                return f"{lat}, {lon}"
        return ""

    df_stations["coords"] = df_stations.apply(extract_coords, axis=1)
    df_stations["location"] = df_stations.apply(
        lambda r: str(r["address"]).strip()
        if pd.notna(r["address"]) and isinstance(r["address"], str) and r["address"].strip() != ""
        else r["coords"],
        axis=1,
    )

    # 合併站點靜態資訊與即時借還車數
    station_cols = [c for c in ["StationUID", "StationID", "station_name", "location"] if c in df_stations.columns]
    avail_cols = [
        c for c in ["StationUID", "StationID", "AvailableRentBikes", "AvailableReturnBikes", "ServiceStatus", "UpdateTime"]
        if c in df_avail.columns
    ]

    join_key = "StationUID" if "StationUID" in df_stations.columns and "StationUID" in df_avail.columns else "StationID"
    merged = pd.merge(
        df_stations[station_cols].drop_duplicates(subset=[join_key]),
        df_avail[avail_cols].drop_duplicates(subset=[join_key]),
        on=join_key,
        how="left",
    )

    # 建立正規化後的目標站點名稱對照表（保留原始名稱方便除錯）
    target_map = {
        normalize_station_name(raw_name): raw_name.strip()
        for raw_name in DOULIU_STATION_NAMES
        if normalize_station_name(raw_name)
    }
    merged["norm_station_name"] = merged["station_name"].apply(normalize_station_name)

    # 依目標站點名稱清單篩選
    is_matched = merged["norm_station_name"].isin(target_map.keys())
    douliu_df = merged[is_matched].copy()

    # 印出清單中有但目前 TDX 資料裡未比對到的站點名稱，方便核對寫法差異
    matched_norms = set(douliu_df["norm_station_name"].dropna())
    unmatched_targets = [orig for norm, orig in target_map.items() if norm not in matched_norms]
    print(f"去重後目標站點數：{len(target_map)}，本次成功比對：{len(douliu_df)}，未比對到：{len(unmatched_targets)}")
    if unmatched_targets:
        print("未比對到的清單站點：", unmatched_targets)

    # 整理最終輸出欄位與時間戳記
    result = pd.DataFrame({
        "fetched_at": fetched_at,
        "station_id": douliu_df.get("StationID"),
        "station_name": douliu_df["station_name"],
        "location": douliu_df["location"],
        "available_rent_bikes": douliu_df.get("AvailableRentBikes"),
        "available_return_bikes": douliu_df.get("AvailableReturnBikes"),
    })

    result = result.sort_values(by=["station_id", "station_name"], na_position="last").reset_index(drop=True)
    return result


def main():
    client_id = os.environ.get("TDX_CLIENT_ID")
    client_secret = os.environ.get("TDX_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError("請設定環境變數 TDX_CLIENT_ID 與 TDX_CLIENT_SECRET")

    tz_tw = timezone(timedelta(hours=8))
    now_tw = datetime.now(tz_tw)
    fetched_at_str = now_tw.strftime("%Y-%m-%d %H:%M:%S")
    date_tag = now_tw.strftime("%Y%m%d")
    time_tag = now_tw.strftime("%H%M")

    token = get_tdx_token(client_id=client_id, client_secret=client_secret)
    stations_data = fetch_json(STATION_URL, token)
    availability_data = fetch_json(AVAILABILITY_URL, token)

    douliu_df = build_douliu_bike_df(stations_data, availability_data, fetched_at_str)
    print(f"[{fetched_at_str}] 最終輸出斗六市站點數：{len(douliu_df)} 筆")

    os.makedirs("data", exist_ok=True)
    output_path = os.path.join("data", f"douliu_bike_{date_tag}_{time_tag}.csv")
    douliu_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"已成功寫入：{output_path}")


if __name__ == "__main__":
    main()
