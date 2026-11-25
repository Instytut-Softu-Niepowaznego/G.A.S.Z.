import geopandas as gpd
import rasterio
import shapely
import streamlit as st
from shapely.geometry import Point, Polygon
import pandas as pd
from pathlib import Path
from streamlit_folium import st_folium
from pyproj import Geod
import matplotlib.pyplot as plt
import rasterio
import numpy as np

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "lab2-geopandas"

rynek = Point(17.9226, 50.6681)          # (x, y) = (longitude, latitude)
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

# 4. -999 is the sensor's error code, not a measurement
df = df[df["pm25"] >= 0].reset_index(drop=True)
report["clean rows"] = len(df)

sensors = gpd.GeoDataFrame(
    df,
    geometry=gpd.points_from_xy(df["lon"], df["lat"]),   # x = lon, y = lat!
    crs="EPSG:4326",
)
sensors_m = sensors.to_crs("EPSG:2180")

st_folium(sensors.explore(column="pm25", cmap="Oranges", marker_kwds={"radius": 6}), width=1000)

districts = gpd.read_file(DATA_DIR / "opole_districts.geojson")
districts.head()

districts = districts.to_crs("EPSG:2180")
districts["area_km2"] = districts.area / 1e6        # m² -> km²

st.write(f"City area: {districts['area_km2'].sum():.1f} km²")
districts.sort_values("area_km2", ascending=False).head()

fig, ax = plt.subplots(figsize=(7, 7))
districts.plot(column="area_km2", cmap="Blues", legend=True,
               edgecolor="white", ax=ax)
ax.set_title("Opole districts by area [km²]")
ax.set_axis_off()

st.pyplot(fig)

joined = gpd.sjoin(
    sensors_m,                                   # left: points
    districts[["name", "geometry"]],             # right: polygons (only the columns we need)
    how="left",
    predicate="within",                          # point lies within polygon
)
joined[["sensor_id", "pm25", "name"]].head()

stats = (joined.groupby("name")
               .agg(pm25_mean=("pm25", "mean"), sensor_count=("pm25", "size"))
               .round(1))

summary = districts.merge(stats, on="name", how="left")
summary.sort_values("pm25_mean", ascending=False).head()

reliable = summary[summary["sensor_count"] >= 3]
reliable.nlargest(3, "pm25_mean")[["name", "pm25_mean", "sensor_count"]]

st_folium(summary.explore(column="pm25_mean", cmap="Oranges", scheme="quantiles", k=5,
                legend_kwds={"caption": "mean PM2.5 [µg/m³]"},
                missing_kwds={"color": "lightgray", "label": "no sensors"}), width=1000)


schools = gpd.read_file(DATA_DIR / "opole_schools.geojson").to_crs("EPSG:2180")

buffers = schools.copy()
buffers["geometry"] = schools.buffer(1500)          # metres, because EPSG:2180
buffers.head(3)

near_schools = gpd.sjoin(sensors_m, buffers[["name", "geometry"]], predicate="within")

st.write("schools:", len(schools))
st.write("schools with a sensor within 500 m:", near_schools["name"].nunique())
st.write(f"mean PM2.5 near schools: {near_schools['pm25'].mean():.1f} µg/m³")

city = districts.union_all()
coverage = buffers.union_all().intersection(city).area / city.area
st.write(f"{coverage:.1%} of the city")

m = districts.explore(color="gray", style_kwds={"fillOpacity": 0.05}, name="districts")
buffers.explore(m=m, color="orange", name="500 m buffers")
sensors_m.explore(m=m, color="black", marker_kwds={"radius": 3}, name="sensors")

st_folium(m, width=1000)

out = Path("wyniki")
out.mkdir(exist_ok=True)

# GeoPackage: many layers in one file, any CRS - the default choice
summary.to_file(out / "pm25.gpkg", layer="districts", driver="GPKG")
sensors_m.to_file(out / "pm25.gpkg", layer="sensors", driver="GPKG")

# GeoJSON: for web applications - always save it in EPSG:4326
summary.to_crs("EPSG:4326").to_file(out / "pm25_districts.geojson", driver="GeoJSON")

gpd.list_layers(out / "pm25.gpkg")

check = gpd.read_file(out / "pm25.gpkg", layer="districts")
st.write(len(check), check.crs)