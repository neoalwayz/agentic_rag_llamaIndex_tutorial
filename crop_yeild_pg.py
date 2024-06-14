def cropYeild(date: str, bbox: list) -> str:
    def input_data():
        input_date = date

        # crop = data['selectedCrop']
        crop =  "Sugarcane"

        print(f"Input Data fetched \ndate: {input_date}\ncrop: {crop}")
        
        return input_date, crop


    ### SENTINEL HUB INSTANCE INFORMATION

    
    config = SHConfig()
    config.instance_id = 'c7deb951-735b-4978-8993-fbe59b03ae15'
    config.sh_client_id = 'dfff811c-7c59-4908-87c1-fb426cd4a768'
    config.sh_client_secret = 'VgL4yiU62gC6ZW5AqIYMvfh16y20edPl'
    config.save()


    ### DEFINING BOUNDING BOX

    def dimensions():
        bbox = BBox(bbox = BBOX, crs = CRS.WGS84)
        print("Bounding Box created")
        
        return bbox


    ### SENTINELHUB API WCS REQUEST FOR FAPAR LAYER
    ### FAPAR --> FRACTION OF ABSORBED PHOTOSYNTHETICALLY ACTIVE RADIATION

    def fapar_layer_call(bbox, input_date):
        wcs_true_color_request = WcsRequest(
            data_collection = DataCollection.SENTINEL2_L2A,
            data_folder = '/SENTINEL_PRODUCTS/FAPAR/',
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
            data_folder = '/SENTINEL_PRODUCTS/LSWI/',
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

    def ghi_calc(input_date, bbox):
        lat = bbox.middle[1]
        lon = bbox.middle[0]
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

    def npp_calc(input_date, sentinel_data, bbox):
        FAPAR = sentinel_data['FAPAR']
        GHI = ghi_calc(input_date, bbox)
        LUE = lue_calc(sentinel_data)
        NPP = FAPAR * GHI * 0.5 * LUE
        NPP[NPP < 0] = 0
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

    def cy_calc(input_date, crop, sentinel_data, bbox):
        NPP = npp_calc(input_date, sentinel_data, bbox)
        HI = harvest_index_dict(crop)         
        cy = NPP * HI * 10
        print(np.amin(cy), np.amax(cy))
        
        return cy


    ### CLIPPING RASTER

    def clipping_raster(geojson_data, cy_path):
        with rasterio.open(cy_path) as src:   
            out_image, out_transform = rasterio.mask.mask(src, geojson_data.geometry, crop = True)
            out_meta = src.meta.copy()
            out_meta.update({"driver": "GTiff",
                            "height": out_image.shape[1],
                            "width": out_image.shape[2],
                            "transform": out_transform})
            
        with rasterio.open(cy_path, "w", **out_meta) as dest:
            dest.write(out_image)

    ### ZONAL STATISTICS 

    def zonal_stats_calc(geojson_data, cy_path):
        cy = zonal_stats(geojson_data,
                        cy_path,
                        band = 1,
                        nodata = np.nan,
                        stats = ['mean'], 
                        geojson_out = True)
        cy_mean_dict = {}
        for i in range(len(cy)):
            cy_mean_dict[cy[i]['id']] = round(cy[i]['properties']['mean'], 2)
        
        print(cy_mean_dict)
            
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

    
    input_date, crop = input_data()
    bbox_tmp = dimensions()
    print(bbox_tmp)
    sentinel_data = sentinel_data_dict(bbox_tmp, input_date)
    transform = rasterio.transform.from_bounds(BBOX[0], BBOX[1], BBOX[2], BBOX[3], sentinel_data['FAPAR'].shape[1], sentinel_data['FAPAR'].shape[0])

    cy_path = 'CY.tiff'
    cy = cy_calc(input_date, crop, sentinel_data, bbox_tmp)
    with rasterio.open(cy_path, 'w', driver = 'GTiff', width = cy.shape[1], height = cy.shape[0], count = 1, dtype = cy.dtype, crs = 'EPSG:4326', transform = transform) as dst:
        dst.write(cy, 1)

    clipping_raster(geojson_data, cy_path)
    cy, cy_mean = zonal_stats_calc(geojson_data, cy_path)
    cy = excel(cy)
    geojson_data = geojson(geojson_data, cy)

    cy.to_excel('/OUTPUT/cy.xlsx')
    geojson_data.to_file('/OUTPUT/cy.geojson')
    with open('/OUTPUT/cy_mean.json', 'w') as outfile:
        json.dump(cy_mean, outfile)

    print('Crop Yield calculated')
