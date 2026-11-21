from datetime import datetime, timezone, timedelta
import os
import pandas as pd
import requests

# TDX OAuth 2.0 Token 端點與雲林縣公共自行車端點（含 /City/ 路徑）
TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
STATION_URL = "https://tdx.transportdata.tw/api/basic/v2/Bike/Station/City/YunlinCounty?$format=JSON"
AVAILABILITY_URL = "https://tdx.transportdata.tw/api/basic/v2/Bike/Availability/City/YunlinCounty?$format=JSON"


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
    """整理站點與即時車況資料，篩選出斗六市站點並加上時間戳記"""
    df_stations = pd.DataFrame(stations_raw)
    df_avail = pd.DataFrame(avail_raw)

    # 解析站點名稱
    if "StationName" in df_stations.columns:
        df_stations["station_name"] = df_stations["StationName"].apply(
            lambda x: x.get("Zh_tw") if isinstance(x, dict) else None
        )
    else:
        df_stations["station_name"] = None

    # 解析站點地址／位置
    if "StationAddress" in df_stations.columns:
        df_stations["address"] = df_stations["StationAddress"].apply(
            lambda x: x.get("Zh_tw") if isinstance(x, dict) else None
        )
    else:
        df_stations["address"] = None

    # 解析行政區與座標
    def extract_town(row):
        pos = row.get("StationPosition")
        if isinstance(pos, dict) and pos.get("Town"):
            return pos.get("Town")
        addr = row.get("address") or ""
        return "斗六市" if "斗六" in addr else ""

    def extract_coords(row):
        pos = row.get("StationPosition")
        if isinstance(pos, dict):
            lat = pos.get("PositionLat")
            lon = pos.get("PositionLon")
            if lat is not None and lon is not None:
                return f"{lat}, {lon}"
        return ""

    df_stations["town"] = df_stations.apply(extract_town, axis=1)
    df_stations["coords"] = df_stations.apply(extract_coords, axis=1)
    df_stations["location"] = df_stations.apply(
        lambda r: r["address"] if pd.notna(r["address"]) and str(r["address"]).strip() != "" else r["coords"],
        axis=1,
    )

    # 合併站點靜態資訊與即時借還車數
    station_cols = [c for c in ["StationUID", "StationID", "station_name", "location", "town"] if c in df_stations.columns]
    avail_cols = [
        c for c in ["StationUID", "StationID", "AvailableRentBikes", "AvailableReturnBikes", "ServiceStatus", "UpdateTime"]
        if c in df_avail.columns
    ]

    join_key = "StationUID" if "StationUID" in df_stations.columns and "StationUID" in df_avail.columns else "StationID"
    merged = pd.merge(
        df_stations[station_cols].drop_duplicates(subset=[join_key]),
        df_avail[avail_cols].drop_duplicates(subset=[join_key]),
        on=join_key,
        how="inner",
    )

    # 篩選斗六市站點
    is_douliu = (
        merged["town"].astype(str).str.contains("斗六", na=False)
        | merged["station_name"].astype(str).str.contains("斗六", na=False)
        | merged["location"].astype(str).str.contains("斗六", na=False)
    )
    douliu_df = merged[is_douliu].copy()

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
    print(f"[{fetched_at_str}] 篩選出斗六市站點數：{len(douliu_df)} 筆")

    os.makedirs("data", exist_ok=True)
    output_path = os.path.join("data", f"douliu_bike_{date_tag}_{time_tag}.csv")
    douliu_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"已成功寫入：{output_path}")


if __name__ == "__main__":
    main()
