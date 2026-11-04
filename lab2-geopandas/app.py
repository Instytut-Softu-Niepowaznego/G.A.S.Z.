from pathlib import Path

import streamlit as st
import pandas as pd
import geopandas as gpd
import rasterio
import shapely
from shapely.geometry import Point, Polygon
from streamlit_folium import st_folium

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parents[1] / "data" / HERE.name

rynek = Point(17.9226, 50.6681)         
square = Polygon([(17.92, 50.66), (17.93, 50.66), (17.93, 50.67), (17.92, 50.67)])


places = gpd.GeoDataFrame(
    {"name": ["Rynek", "Square"]},
    geometry=[rynek, square],
    crs="EPSG:4326",
)

raw = pd.read_csv(DATA_DIR / "pm25_sensors.csv", parse_dates=["measured_at"])

df = raw.copy()
report = {"input rows": len(df)}

# 1. Duplicates - the same message sent twice
df = df.drop_duplicates()
report["after drop_duplicates"] = len(df)

# 2. Rows without coordinates cannot be placed on a map
df = df.dropna(subset=["lat", "lon"])
report["after dropna"] = len(df)

# 3. Swapped coordinates: in Poland lat is 49-55 and lon is 14-24
swapped = df["lat"].between(14, 24.5) & df["lon"].between(49, 55)
df.loc[swapped, ["lat", "lon"]] = df.loc[swapped, ["lon", "lat"]].to_numpy()
report["swapped rows fixed"] = int(swapped.sum())

sensors = gpd.GeoDataFrame(
    df,
    geometry=gpd.points_from_xy(df["lon"], df["lat"]),   # x = lon, y = lat!
    crs="EPSG:4326",
)
sensors.head()

print(sensors.geom_type.unique())
print(sensors.crs)
print(sensors.total_bounds)              # [minx, miny, maxx, maxy]

m = sensors.explore(column="pm25", cmap="Oranges", marker_kwds={"radius": 6})
st_folium(m, height=500, use_container_width=True, returned_objects=[])
