print("crop-yield-script")

from sentinelhub import SHConfig
import datetime
import pandas as pd
import numpy as np
from sentinelhub import CRS, BBox, DataCollection, MimeType, WcsRequest
from sentinelhub import CustomUrlParam
import geopandas as gpd
import rasterio
import rasterio.mask
from sentinelhub import CRS, BBox, DataCollection, MimeType, WcsRequest, CustomUrlParam
import requests
import json
import geopandas as gpd
from rasterstats import zonal_stats
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")


### INPUT DATA 

def input_data():
    with open('/home/ubuntu/flask-dev/Flaskk/ev/Parameters/CROP_YIELD/INPUT_DATA/crop_yield_data.json', 'r') as f:
        data = json.load(f)

    input_date = data['date']
    input_date = datetime.fromisoformat(input_date.replace('Z', '+00:00'))
    input_date = input_date.date().isoformat()

    crop = data['selectedCrop']

    print("Input Data fetched")
    
    return input_date, crop


### SENTINEL HUB INSTANCE INFORMATION

from sentinelhub import SHConfig
config = SHConfig()
config.instance_id = 'c7deb951-735b-4978-8993-fbe59b03ae15'
config.sh_client_id = 'dfff811c-7c59-4908-87c1-fb426cd4a768'
config.sh_client_secret = 'VgL4yiU62gC6ZW5AqIYMvfh16y20edPl'
config.save()


### JSON TO SHAPEFILE CONVERSION

def geojson_to_shp(geojson_data):
    geojson_data.to_file('/home/ubuntu/flask-dev/Flaskk/ev/Parameters/CROP_YIELD/SHAPEFILE/cy_shp.shp')
    shp = gpd.read_file('/home/ubuntu/flask-dev/Flaskk/ev/Parameters/CROP_YIELD/SHAPEFILE/cy_shp.shp')
    shp = shp.to_crs(epsg = 4326)
    shp['centroid'] = shp.centroid
    
    return shp


### DEFINING BOUNDING BOX

def dimensions(geojson_data, input_date):
    shp = geojson_to_shp(geojson_data)
    minx, miny, maxx, maxy = shp.total_bounds
    extent = [minx, miny, maxx, maxy]
    bbox = BBox(bbox=extent, crs=CRS.WGS84)
    FAPAR = fapar_layer_call(bbox, input_date)
    transform = rasterio.transform.from_bounds(extent[0], extent[1], extent[2], extent[3], FAPAR.shape[1], FAPAR.shape[0])

    print("Bounding Box created")
    
    return bbox, transform


### SENTINELHUB API WCS REQUEST FOR FAPAR LAYER
### FAPAR --> FRACTION OF ABSORBED PHOTOSYNTHETICALLY ACTIVE RADIATION

def fapar_layer_call(bbox, input_date):
    wcs_true_color_request = WcsRequest(
        data_collection = DataCollection.SENTINEL2_L2A,
        data_folder = '/home/ubuntu/flask-dev/Flaskk/ev/Parameters/CROP_YIELD/SENTINEL_PRODUCTS/FAPAR/',
        layer = 'FAPAR',
        bbox = bbox,
        time = input_date,
        resx = '10m',
        resy = '10m',
        image_format = MimeType.TIFF,
        custom_url_params = {
            CustomUrlParam.SHOWLOGO: False
        },
        config = config
    )
    wcs_true_color_img = wcs_true_color_request.get_data()
    FAPAR = wcs_true_color_img[-1]

    print("FAPAR fetched")
    
    return FAPAR


### SENTINELHUB API WCS REQUEST FOR LSWI LAYER
### LSWI --> LAND SURFACE WATER INDEX

def lswi_layer_call(bbox, input_date):
    wcs_true_color_request = WcsRequest(
        data_collection = DataCollection.SENTINEL2_L2A,
        data_folder = '/home/ubuntu/flask-dev/Flaskk/ev/Parameters/CROP_YIELD/SENTINEL_PRODUCTS/LSWI/',
        layer = 'LSWI',
        bbox = bbox,
        time = input_date,
        resx = '10m',
        resy = '10m',
        image_format = MimeType.TIFF,
        custom_url_params = {
            CustomUrlParam.SHOWLOGO: False
        },
        config = config
    )
    wcs_true_color_img = wcs_true_color_request.get_data()
    LSWI = wcs_true_color_img[-1]

    print("LSWI fetched")
    
    return LSWI


### SENTINEL DATA DICTINOARY

def sentinel_data_dict(bbox, input_date):
    FAPAR = fapar_layer_call(bbox, input_date)
    LSWI = lswi_layer_call(bbox, input_date)

    sentinel_data = {
        'FAPAR' : FAPAR,
        'LSWI' : LSWI
    }

    return sentinel_data


### WATER STRESS SCALAR (W) CALCULATIONS

def w_calc(sentinel_data):
    LSWI = sentinel_data['LSWI']
    LSWI_max = np.amax(LSWI)
    w = (1 - LSWI) / (1 + LSWI_max)

    print("Water Stres Scalar calculated")
    
    return w


### LIGHT USE EFFICIENCY (LUE) CALCULATIONS

def lue_calc(sentinel_data):
    e0 = 3.22          # MAXIMUM VALUE OF LUE
    w = w_calc(sentinel_data)
    LUE = e0 * w

    print("LUE calculated")
    
    return LUE


### GLOBAL HORIZONTAL IRRADIANCE CALCULATIONS

def ghi_calc(geojson_data, input_date):
    shp = geojson_to_shp(geojson_data)
    lat = shp.loc[0, 'centroid'].y
    lon = shp.loc[0, 'centroid'].x
    API_KEY = 'eb8cf696ffe68ba33f4b7c3b25e45d5c' #OpenWeatherMap @ARMS4AI
    #-------Call this API Once-------
    response = requests.get(f"https://api.openweathermap.org/energy/1.0/solar/data?lat={lat}&lon={lon}&date={input_date}&appid={API_KEY}")
    data = response.json()

    GHI = 0
    for i in data["irradiance"]["daily"]:
        GHI = i['clear_sky']['ghi']
    GHI = (GHI * 3.6) / 1000
    
    return GHI


### NET PRIMARY PRODUCTIVITY (NPP) CALCULATIONS

def npp_calc(geojson_data, input_date, sentinel_data):
    FAPAR = sentinel_data['FAPAR']
    GHI = ghi_calc(geojson_data, input_date)
    LUE = lue_calc(sentinel_data)
    NPP = FAPAR * GHI * 0.5 * LUE
    nodata = 0
    NPP[NPP < 0] = nodata

    print("NPP calculated")
    
    return NPP


### HARVEST INDEX DICTIONARY

def harvest_index_dict(crop):
    harvest_index = {
        "Potato" : 0.2,
        "Cotton" : 0.008,
        "Wheat" : 0.01,
        "Corn" : 0.045,
        "Barley" : 0.01,
        "Sunflower" : 0.01,
        "Sugarcane" : 0.98,
        "Chilli"    : 0.017
    }
    
    return harvest_index[crop]


### CROP YIELD CALCULATIONS

def cy_calc(geojson_data, input_date, crop, sentinel_data):
    NPP = npp_calc(geojson_data, input_date, sentinel_data)
    HI = harvest_index_dict(crop)         
    cy = NPP * HI * 10

    print(np.amin(cy), np.amax(cy))
    
    return cy


### CLIPPING RASTER

def clipping_raster(geojson_data, cy_path):
    shp = geojson_to_shp(geojson_data)
    with rasterio.open(cy_path) as src:   
        out_image, out_transform = rasterio.mask.mask(src, shp.geometry, crop = True)
        out_meta = src.meta.copy()
        out_meta.update({"driver": "GTiff",
                         "height": out_image.shape[1],
                         "width": out_image.shape[2],
                         "transform": out_transform})
        
    with rasterio.open(cy_path, "w", **out_meta) as dest:
        dest.write(out_image)


### ZONAL STATISTICS 

def zonal_stats_calc(geojson_data, cy_path):
    shp = geojson_to_shp(geojson_data)
    cy = zonal_stats(shp,
                     cy_path,
        			 band = 1,
                     nodata = np.nan,
                     stats = ['mean'], 
                     geojson_out = True)

    cy_mean_dict = {}
    for i in range(len(cy)):
        cy_mean_dict[cy[i]['id']] = round(cy[i]['properties']['mean'], 2)
        
    cy_mean = round(sum(cy_mean_dict.values()) / len(cy_mean_dict), 2)

    return cy, cy_mean


### EXCEL GENERATION

def excel(cy):
    cy_excel = pd.DataFrame()
    for i in range(len(cy)):
        cy_excel = cy_excel.append(cy[i]['properties'], ignore_index=True)

    return cy_excel


### GEOJSON GENERATION

def geojson(geojson_data, cy):
    geojson_data['Crop_Yield'] = " "
    for i in range(len(geojson_data)):
        geojson_data['Crop_Yield'][i] = cy['mean'][i]

    return geojson_data


### MAIN FUNCTION

def main():
    input_date, crop = input_data()
    geojson_data = gpd.read_file('/home/ubuntu/flask-dev/Flaskk/ev/Parameters/CROP_YIELD/INPUT_DATA/geojson_data.geojson')
    bbox, transform = dimensions(geojson_data, input_date)
    sentinel_data = sentinel_data_dict(bbox, input_date)

    cy_path = '/home/ubuntu/flask-dev/Flaskk/ev/Parameters/CROP_YIELD/RASTERS/CY.tiff'
    cy = cy_calc(geojson_data, input_date, crop, sentinel_data)
    with rasterio.open(cy_path, 'w', driver = 'GTiff', width = cy.shape[1], height = cy.shape[0], count = 1, dtype = cy.dtype, crs = 'EPSG:4326', transform = transform) as dst:
        dst.write(cy, 1)

    clipping_raster(geojson_data, cy_path)
    cy, cy_mean = zonal_stats_calc(geojson_data, cy_path)
    cy = excel(cy)
    geojson_data = geojson(geojson_data, cy)

    cy.to_excel('/home/ubuntu/flask-dev/Flaskk/ev/Parameters/CROP_YIELD/OUTPUT/cy.xlsx')
    geojson_data.to_file('/home/ubuntu/flask-dev/Flaskk/ev/Parameters/CROP_YIELD/OUTPUT/cy.geojson')
    with open('/home/ubuntu/flask-dev/Flaskk/ev/Parameters/CROP_YIELD/OUTPUT/cy_mean.json', 'w') as outfile:
        json.dump(cy_mean, outfile)

    print('Crop Yield calculated')

if __name__ == "__main__":
    main()