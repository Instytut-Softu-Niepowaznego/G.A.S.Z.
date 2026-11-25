"""NDVI z Sentinel-2 (B04 + B08) przy pomocy rasterio.

Uruchom:  streamlit run ndvi_app.py
"""
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
import rasterio.mask
import streamlit as st
from rasterio.warp import Resampling, calculate_default_transform, reproject

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "lab2-geopandas"
OUT_DIR = Path(__file__).resolve().parent / "wyniki"
OUT_DIR.mkdir(exist_ok=True)

B04_PATH = DATA_DIR / "S2_L2A_2026-10-06_B04.tiff"
B08_PATH = DATA_DIR / "S2_L2A_2026-10-06_B08.tiff"
NDVI_PATH = OUT_DIR / "ndvi.tif"

st.title("NDVI – Opole, Sentinel-2 (2026-10-06)")

# ---------------------------------------------------------------- 1. Wczytanie
red_src = rasterio.open(B04_PATH)
nir_src = rasterio.open(B08_PATH)

same_grid = (red_src.crs == nir_src.crs
             and red_src.transform == nir_src.transform
             and red_src.shape == nir_src.shape)

st.header("1. Metadane rastrów")
st.table(pd.DataFrame({
    "B04 (red)": [str(red_src.crs), red_src.shape, red_src.dtypes[0], red_src.res],
    "B08 (nir)": [str(nir_src.crs), nir_src.shape, nir_src.dtypes[0], nir_src.res],
}, index=["CRS", "shape", "dtype", "res"]).astype(str))
st.write("Ta sama siatka:", same_grid)

# ------------------------------------------------- 2. Reprojekcja do EPSG:2180
dst_crs = "EPSG:2180"
dst_transform, width, height = calculate_default_transform(
    red_src.crs, dst_crs, red_src.width, red_src.height, *red_src.bounds,
    resolution=10)                   # Sentinel-2 B04/B08 are natively 10 m


def warp(src):                       # put any band onto the target grid
    out = np.full((height, width), np.nan, dtype="float32")
    reproject(source=rasterio.band(src, 1), destination=out,
              dst_transform=dst_transform, dst_crs=dst_crs,
              dst_nodata=np.nan, resampling=Resampling.bilinear)
    return np.ma.masked_invalid(out)


red, nir = warp(red_src), warp(nir_src)
red_src.close()
nir_src.close()

# --------------------------------------------------------------------- 3. NDVI
with np.errstate(divide="ignore", invalid="ignore"):    # 0 / 0 where both bands are 0
    ndvi = (nir - red) / (nir + red)
ndvi = np.ma.masked_invalid(ndvi)

st.header("2. NDVI")
st.write(f"min {ndvi.min():.2f}, max {ndvi.max():.2f}, mean {ndvi.mean():.2f}")

fig, ax = plt.subplots(figsize=(8, 7))
im = ax.imshow(ndvi, cmap="RdYlGn", vmin=-1, vmax=1)
fig.colorbar(im, ax=ax, label="NDVI")
ax.set_title("NDVI (EPSG:2180, 10 m)")
ax.set_axis_off()
st.pyplot(fig)

# --------------------------------------------------------- 4. Klasy i powierzchnie
classes = np.digitize(ndvi.filled(np.nan), bins=[0.0, 0.2, 0.5])   # 0, 1, 2, 3
classes = np.ma.masked_where(ndvi.mask, classes)

pixel_area_m2 = abs(dst_transform.a * dst_transform.e)            # 100 m²
area_ha = np.bincount(classes.compressed(), minlength=4) * pixel_area_m2 / 10_000

labels = ["woda / brak (<0)", "zabudowa / gleba (0–0.2)",
          "rzadka roślinność (0.2–0.5)", "gęsta roślinność (≥0.5)"]
st.header("3. Klasy NDVI")
area_df = pd.DataFrame({"klasa": labels, "powierzchnia [ha]": area_ha.round(1)})
area_df["udział [%]"] = (100 * area_ha / area_ha.sum()).round(1)
st.dataframe(area_df, hide_index=True)

fig, ax = plt.subplots(figsize=(8, 7))
im = ax.imshow(classes, cmap=plt.get_cmap("RdYlGn", 4), vmin=-0.5, vmax=3.5)
cbar = fig.colorbar(im, ax=ax, ticks=range(4))
cbar.ax.set_yticklabels(labels)
ax.set_axis_off()
st.pyplot(fig)

# ------------------------------------------------------------ 5. Zapis GeoTIFF
with rasterio.open(B04_PATH) as src:
    profile = src.profile                     # start from the input's profile…

profile.update(                               # …and describe the grid we computed NDVI on
    crs=dst_crs, transform=dst_transform, width=width, height=height,
    dtype="float32", count=1, nodata=np.nan, compress="deflate",
)

with rasterio.open(NDVI_PATH, "w", **profile) as dst:
    dst.write(ndvi.filled(np.nan).astype("float32"), 1)
    dst.set_band_description(1, "NDVI")

st.success(f"Zapisano {NDVI_PATH.relative_to(OUT_DIR.parent)}")

# ------------------------------------------- 6. Statystyki strefowe (dzielnice)
with rasterio.open(NDVI_PATH) as src:
    zones = gpd.read_file(DATA_DIR / "opole_districts.geojson").to_crs(src.crs)   # same CRS as the raster!
    pixel_area = abs(src.transform.a * src.transform.e)
    for i, zone in zones.iterrows():
        try:
            clipped, _ = rasterio.mask.mask(src, [zone.geometry], crop=True, nodata=np.nan)
            values = clipped[np.isfinite(clipped)]
        except ValueError:                    # zone lies entirely outside the scene
            values = np.array([])
        zones.loc[i, "coverage"] = values.size * pixel_area / zone.geometry.area   # part of the zone inside the scene
        zones.loc[i, "ndvi_mean"] = values.mean() if values.size else np.nan

st.header("4. Średnie NDVI w dzielnicach")
st.dataframe(zones[["name", "ndvi_mean", "coverage"]]
             .sort_values("ndvi_mean", ascending=False)
             .round(3), hide_index=True)

fig, ax = plt.subplots(figsize=(7, 7))
zones.plot(column="ndvi_mean", cmap="RdYlGn", legend=True,
           edgecolor="white", ax=ax,
           missing_kwds={"color": "lightgray"})
ax.set_title("Średnie NDVI w dzielnicach Opola")
ax.set_axis_off()
st.pyplot(fig)

zones.to_file(OUT_DIR / "ndvi_districts.gpkg", driver="GPKG")
