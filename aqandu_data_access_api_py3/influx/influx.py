import requests
import sys
import time

from datetime import datetime, timedelta
from flask import jsonify, request, Blueprint
from influxdb import InfluxDBClient
from pymongo import MongoClient
from werkzeug.local import LocalProxy

# from .. import app
from flask import current_app


influx = Blueprint('influx', __name__)
logger = LocalProxy(lambda: current_app.logger)

# lookup table to transform querString to influx column name
lookupQueryParameterToInflux = {
    'pm25': '\"pm2.5 (ug/m^3)\"',
    'altitude': '\"Altitude (m)\"',
    'humidity': '\"Humidity (%)\"',
    'id': 'ID',
    'latitude': 'Latitude',
    'longitude': 'Longitude',
    'ozon': '\"Ozon concentration (ppb)\"',
    'pressure': '\"Pressure (Pa)\"',
    'sensor_model': '\"Sensor Model\"',
    'sensor_source': '\"Sensor Source\"',
    'sensor_version': '\"Sensor Version\"',
    'sensor_error': '\"Sensor error code\"',
    'solar_radiation': '\"Solar radiation (W/m**2)\"',
    'start': 'Start',
    'temp': '\"Temp (*C)\"',
    'wind_direction': '\"Wind direction (compass degree)\"',
    'wind_gust': '\"Wind gust (m/s)\"',
    'wind_speed': '\"Wind speed (m/s)\"',
    'pm1': '\"pm1.0 (ug/m^3)\"',
    'pm10': '\"pm10.0 (ug/m^3)\"',
    'posix': 'POSIX',
    'secActive': 'SecActive'
}


lookupParameterToAirUInflux = {
    'altitude': 'Altitude',
    'humidity': 'Humidity',
    'latitude': 'Latitude',
    'longitude': 'Longitude',
    'pm1': 'PM1',
    'pm10': 'PM10',
    'pm25': '\"PM2.5\"',
    'temperature': 'Temperature',
    'posix': 'POSIX',
    'secActive': 'SecActive',
    'errors': 'Errors',
}

# with app.app_context():
#     influxClientPolling = InfluxDBClient(
#             host=current_app.config['INFLUX_HOST'],
#             port=current_app.config['INFLUX_PORT'],
#             username=current_app.config['INFLUX_USERNAME'],
#             password=current_app.config['INFLUX_PASSWORD'],
#             database=current_app.config['INFLUX_POLLING_DATABASE'],
#             ssl=current_app.config['SSL'],
#             verify_ssl=current_app.config['SSL'])
#
#     influxClientAirU = InfluxDBClient(
#             host=current_app.config['INFLUX_HOST'],
#             port=current_app.config['INFLUX_PORT'],
#             username=current_app.config['INFLUX_USERNAME'],
#             password=current_app.config['INFLUX_PASSWORD'],
#             database=current_app.config['INFLUX_AIRU_DATABASE'],
#             ssl=current_app.config['SSL'],
#             verify_ssl=current_app.config['SSL'])


@influx.route('/api/liveSensors', methods=['GET'])
def getLiveSensors():
    """Get sensors that are active (pushed data) since yesterday (beginning of day)"""

    logger.info('liveSensors request started')

    now = datetime.now()
    yesterday = now - timedelta(days=1)

    yesterdayBeginningOfDay = yesterday.replace(hour=00, minute=00, second=00)
    yesterdayStr = yesterdayBeginningOfDay.strftime('%Y-%m-%dT%H:%M:%SZ')

    influxClientPolling = InfluxDBClient(
                host=current_app.config['INFLUX_HOST'],
                port=current_app.config['INFLUX_PORT'],
                username=current_app.config['INFLUX_USERNAME'],
                password=current_app.config['INFLUX_PASSWORD'],
                database=current_app.config['INFLUX_POLLING_DATABASE'],
                ssl=current_app.config['SSL'],
                verify_ssl=current_app.config['SSL'])

    queryInflux = "SELECT ID, \"Sensor Source\", Latitude, Longitude, LAST(\"pm2.5 (ug/m^3)\") AS pm25, \"Sensor Model\" " \
                  "FROM airQuality WHERE time >= '" + yesterdayStr + "' " \
                  "GROUP BY ID, Latitude, Longitude, \"Sensor Source\"" \
                  "LIMIT 400"

    start = time.time()
    data = influxClientPolling.query(queryInflux, epoch='ms')
    data = data.raw

    dataSeries = list(map(lambda x: dict(zip(x['columns'], x['values'][0])), data['series']))

    liveAirUs = getAllCurrentlyLiveAirUs()
    logger.info(liveAirUs)

    influxClientAirU = InfluxDBClient(
                host=current_app.config['INFLUX_HOST'],
                port=current_app.config['INFLUX_PORT'],
                username=current_app.config['INFLUX_USERNAME'],
                password=current_app.config['INFLUX_PASSWORD'],
                database=current_app.config['INFLUX_AIRU_DATABASE'],
                ssl=current_app.config['SSL'],
                verify_ssl=current_app.config['SSL'])

    for airU in liveAirUs:
        queryInfluxAirU_lat = "SELECT MEAN(Latitude) " \
                              "FROM " + current_app.config['INFLUX_AIRU_LATITUDE_MEASUREMENT'] + ""\
                              " WHERE ID = '" + airU['mac'] + "' and time >= '" + yesterdayStr + "'" \

        dataAirU_lat = influxClientAirU.query(queryInfluxAirU_lat, epoch='ms')
        dataAirU_lat = dataAirU_lat.raw

        avgLat = dataAirU_lat['series'][0]['values'][0][1]

        queryInfluxAirU_lng = "SELECT MEAN(Longitude) " \
                              "FROM " + current_app.config['INFLUX_AIRU_LONGITUDE_MEASUREMENT'] + ""\
                              " WHERE ID = '" + airU["mac"] + "' and time >= '" + yesterdayStr + "' " \

        dataAirU_lng = influxClientAirU.query(queryInfluxAirU_lng, epoch='ms')
        dataAirU_lng = dataAirU_lng.raw

        avgLng = dataAirU_lng['series'][0]['values'][0][1]

        anAirU = {"ID": airU['mac'], "Latitude": avgLat, "Longitude": avgLng, "Sensor Source": 'AirU'}
        dataSeries.append(anAirU)

    end = time.time()

    print("*********** Time to download:", end - start)

    return jsonify(dataSeries)


@influx.route('/api/sensorsLonger', methods=['GET'])
def getAllSensorsLonger():

    logger.info('sensorsLonger request started')

    TIMESTAMP = datetime.now().isoformat()

    influxClientPolling = InfluxDBClient(
                host=current_app.config['INFLUX_HOST'],
                port=current_app.config['INFLUX_PORT'],
                username=current_app.config['INFLUX_USERNAME'],
                password=current_app.config['INFLUX_PASSWORD'],
                database=current_app.config['INFLUX_POLLING_DATABASE'],
                ssl=current_app.config['SSL'],
                verify_ssl=current_app.config['SSL'])

    stations = {}

    # DAQ
    DAQ_SITES = [{
        'ID': 'Rose Park',
        'dataFeed': 'http://air.utah.gov/xmlFeed.php?id=rp',
        'lat': 40.7955,
        'lon': -111.9309,
        'elevation': 1295,
    }, {
        'ID': 'Hawthorne',
        'dataFeed': 'http://air.utah.gov/xmlFeed.php?id=slc',
        'lat': 40.7343,
        'lon': -111.8721,
        'elevation': 1306
    }, {
        'ID': 'Herriman',
        'dataFeed': 'http://air.utah.gov/xmlFeed.php?id=h3',
        'lat': 40.496408,
        'lon': -112.036305,
        'elevation': 1534
    }, {
        'ID': 'Bountiful',
        'dataFeed': 'http://air.utah.gov/xmlFeed.php?id=bv',
        'lat': 40.903,
        'lon': -111.8845,
        'elevation': None
    }, {
        'ID': 'Magna (Met only)',
        'dataFeed': 'http://air.utah.gov/xmlFeed.php?id=mg',
        'lat': 40.7068,
        'lon': -112.0947,
        'elevation': None
    }]

    start = time.time()

    for aStation in DAQ_SITES:
        stations[str(aStation['ID'])] = {'ID': aStation['ID'], 'Latitude': aStation['lat'], 'Longitude': aStation['lon'], 'elevation': aStation['elevation']}

    # PURPLE AIR
    try:
        purpleAirData = requests.get("https://map.purpleair.org/json")
        purpleAirData.raise_for_status()
    except requests.exceptions.HTTPError as e:
        sys.stderr.write('%s\tProblem acquiring PurpleAir data (https://map.purpleair.org/json);\t%s.\n' % (TIMESTAMP, e))
        return []
    except requests.exceptions.Timeout as e:
        sys.stderr.write('%s\tProblem acquiring PurpleAir data (https://map.purpleair.org/json);\t%s.\n' % (TIMESTAMP, e))
        return []
    except requests.exceptions.TooManyRedirects as e:
        sys.stderr.write('%s\tProblem acquiring PurpleAir data (https://map.purpleair.org/json);\t%s.\n' % (TIMESTAMP, e))
        return []
    except requests.exceptions.RequestException as e:
        sys.stderr.write('%s\tProblem acquiring PurpleAir data (https://map.purpleair.org/json);\t%s.\n' % (TIMESTAMP, e))
        return []

    purpleAirData = purpleAirData.json()['results']

    for aStation in purpleAirData:
        stations[str(aStation['ID'])] = {'ID': aStation['ID'], 'Latitude': aStation['Lat'], 'Longitude': aStation['Lon'],  'elevation': None}

    # MESOWEST
    mesowestURL = 'http://api.mesowest.net/v2/stations/timeseries?recent=15&token=demotoken&stid=mtmet,wbb,NAA,MSI01,UFD10,UFD11&vars=PM_25_concentration'

    try:
        mesowestData = requests.get(mesowestURL)
        mesowestData.raise_for_status()
    except requests.exceptions.HTTPError as e:
        # statusCode = e.response.status_code
        sys.stderr.write('%s\tProblem acquiring Mesowest data;\t%s.\n' % (TIMESTAMP, e))
        return []
    except requests.exceptions.Timeout as e:
        # Maybe set up for a retry, or continue in a retry loop
        sys.stderr.write('%s\tProblem acquiring Mesowest data;\t%s.\n' % (TIMESTAMP, e))
        return []
    except requests.exceptions.TooManyRedirects as e:
        # Tell the user their URL was bad and try a different one
        sys.stderr.write('%s\tProblem acquiring Mesowest data;\t%s.\n' % (TIMESTAMP, e))
        return []
    except requests.exceptions.RequestException as e:
        # catastrophic error. bail.
        sys.stderr.write('%s\tProblem acquiring Mesowest data;\t%s.\n' % (TIMESTAMP, e))
        return []

    mesowestData = mesowestData.json()['STATION']

    for aStation in mesowestData:
        stations[str(aStation['STID'])] = {'ID': aStation['STID'], 'Latitude': aStation['LATITUDE'], 'Longitude': aStation['LONGITUDE'],  'elevation': aStation['ELEVATION']}

    end = time.time()

    query = "SHOW TAG VALUES from airQuality WITH KEY = ID"
    data = influxClientPolling.query(query, epoch=None)
    data = data.raw

    theValues = data['series'][0]['values']
    allIDs = list(map(lambda x: str(x[1]), theValues))
    print(stations)
    print(allIDs)

    stationstoBeShowed = []
    for anID in allIDs:
        sensorAvailable = stations.get(anID)

        if sensorAvailable is not None:
            stationstoBeShowed.append(sensorAvailable)

    print(stationstoBeShowed)

    print("*********** Time to download:", end - start, '***********')

    return jsonify(stations)

# get all ID tags
# for each tag check purpleAir, DAQ and mesowest for the location data


# /api/rawDataFrom?id=1010&sensorSource=PurpleAir&start=2017-10-01T00:00:00Z&end=2017-10-02T00:00:00Z&show=all
# /api/rawDataFrom?id=1010&start=2017-10-01T00:00:00Z&end=2017-10-02T00:00:00Z&show=pm25,pm1
@influx.route('/api/rawDataFrom', methods=['GET'])
def getRawDataFrom():

    airUdbs = ['altitude', 'humidity', 'latitude', 'longitude', 'pm1', 'pm25', 'pm10', 'posix', 'secActive', 'temperature']

    logger.info('rawDataFrom request started')

    queryParameters = request.args
    print(queryParameters)
    # jsonParameters = request.get_json(force=True)
    # print('jsonParameters', jsonParameters)

# TODO get the data for airUs
    if queryParameters['sensorSource'] == 'airu':
        print('airU')
        logger.info(queryParameters['sensorSource'])

        start = time.time()

        # create createSelection
        whatToShow = queryParameters['show'].split(',')

        # http://0.0.0.0:5000/api/rawDataFrom?id=D0B5C2F31E1F&sensorSource=AirU&start=2017-12-02T22:17:00Z&end=2017-12-03T22:17:00Z&show=all
        if 'all' in whatToShow:

            influxClientAirU = InfluxDBClient(
                        host=current_app.config['INFLUX_HOST'],
                        port=current_app.config['INFLUX_PORT'],
                        username=current_app.config['INFLUX_USERNAME'],
                        password=current_app.config['INFLUX_PASSWORD'],
                        database=current_app.config['INFLUX_AIRU_DATABASE'],
                        ssl=current_app.config['SSL'],
                        verify_ssl=current_app.config['SSL'])

            # query each db
            dataSeries = []
            for aDB in airUdbs:

                queryAirU = "SELECT ID, SensorModel, " + lookupParameterToAirUInflux.get(aDB) + " FROM " + aDB + " " \
                            "WHERE ID = '" + queryParameters['id'] + "' " \
                            "AND time >= '" + queryParameters['start'] + "' AND time <= '" + queryParameters['end'] + "' "

                print(queryAirU)

                dataAirU = influxClientAirU.query(queryAirU, epoch=None)
                dataAirU = dataAirU.raw

                valuesAirU = dataAirU['series'][0]['values']
                columnsAirU = dataAirU['series'][0]['columns']

                if not dataSeries:
                    dataSeries = list(map(lambda x: dict(zip(columnsAirU, x)), valuesAirU))
                else:
                    newDataSeries = list(map(lambda x: dict(zip(columnsAirU, x)), valuesAirU))

                    # print(list(zip(dataSeries, newDataSeries)))
                    # as a security I add the timestamp from the merged db, the difference in timestamps are in the 0.1 milisecond (0.0001)
                    # dataSeries = list(map(lambda y: {**y[0], **y[1], 'time_' + aDB: y[1]['time']} if y[0]['time'].split('.')[0] == y[1]['time'].split('.')[0] else {0}, list(zip(dataSeries, newDataSeries))))

                    tmpList = []
                    for dict1, dict2 in list(zip(dataSeries, newDataSeries)):
                        # print(elem1, elem2)
                        if dict1['time'].split('.')[0] == dict2['time'].split('.')[0]:
                            # replace the time attribute with a new key so it does not copy over the dict1's time when being merged
                            dict2['time_' + aDB] = dict2.pop('time')
                            mergedObject = mergeTwoDicts(dict1, dict2)

                            tmpList.append(mergedObject)

                    dataSeries = tmpList

                    # dataSeries = [{y[0], y[1]} for elem in list(zip(dataSeries, newDataSeries)) if y[0]['time'].split('.')[0] == y[1]['time'].split('.')[0]]

        end = time.time()

    else:

        influxClientPolling = InfluxDBClient(
                    host=current_app.config['INFLUX_HOST'],
                    port=current_app.config['INFLUX_PORT'],
                    username=current_app.config['INFLUX_USERNAME'],
                    password=current_app.config['INFLUX_PASSWORD'],
                    database=current_app.config['INFLUX_POLLING_DATABASE'],
                    ssl=current_app.config['SSL'],
                    verify_ssl=current_app.config['SSL'])

        # TODO do some parameter checking
        # TODO check if queryParameters exist if not write excpetion

        selectString = createSelection('raw', queryParameters)

        query = "SELECT " + selectString + " FROM airQuality " \
                "WHERE ID = '" + queryParameters['id'] + "' " \
                "AND time >= '" + queryParameters['start'] + "' AND time <= '" + queryParameters['end'] + "' "
        print(query)
        start = time.time()

        data = influxClientPolling.query(query, epoch=None)
        data = data.raw

        print(data)

        theValues = data['series'][0]['values']
        theColumns = data['series'][0]['columns']

        # pmTimeSeries = list(map(lambda x: {'time': x[0], 'pm25': x[1]}, theValues))
        dataSeries = list(map(lambda x: dict(zip(theColumns, x)), theValues))

        end = time.time()

    print("*********** Time to download:", end - start, '***********')

    return jsonify(dataSeries)


# http://0.0.0.0:5000/api/processedDataFrom?id=1010&start=2017-10-01T00:00:00Z&end=2017-10-02T00:00:00Z&function=mean&functionArg=pm25&timeInterval=30m
@influx.route('/api/processedDataFrom', methods=['GET'])
def getProcessedDataFrom():

    logger.info('processedDataFrom request started')

    influxClientPolling = InfluxDBClient(
                host=current_app.config['INFLUX_HOST'],
                port=current_app.config['INFLUX_PORT'],
                username=current_app.config['INFLUX_USERNAME'],
                password=current_app.config['INFLUX_PASSWORD'],
                database=current_app.config['INFLUX_POLLING_DATABASE'],
                ssl=current_app.config['SSL'],
                verify_ssl=current_app.config['SSL'])

    queryParameters = request.args
    print(queryParameters)

    # TODO do some parameter checking
    # TODO check if queryParameters exist if not write excpetion

    selectString = createSelection('processed', queryParameters)

    query = "SELECT " + selectString + " FROM airQuality " \
            "WHERE ID = '" + queryParameters['id'] + "' " \
            "AND time >= '" + queryParameters['start'] + "' AND time <= '" + queryParameters['end'] + "' GROUP BY time(" + queryParameters['timeInterval'] + ")"

    start = time.time()

    data = influxClientPolling.query(query, epoch=None)
    data = data.raw

    # parse the data
    theValues = data['series'][0]['values']
    pmTimeSeries = list(map(lambda x: {time: x[0], 'pm2.5 (ug/m^3)': x[1]}, theValues))

    # print(pmTimeSeries)

    end = time.time()

    print("*********** Time to download:", end - start, '***********')

    return jsonify(pmTimeSeries)


# http://0.0.0.0:5000/api/lastValue?fieldKey=pm25
@influx.route('/api/lastValue', methods=['GET'])
def getLastValuesForLiveSensor():

    logger.info('lastPM request started')

    influxClientPolling = InfluxDBClient(
                host=current_app.config['INFLUX_HOST'],
                port=current_app.config['INFLUX_PORT'],
                username=current_app.config['INFLUX_USERNAME'],
                password=current_app.config['INFLUX_PASSWORD'],
                database=current_app.config['INFLUX_POLLING_DATABASE'],
                ssl=current_app.config['SSL'],
                verify_ssl=current_app.config['SSL'])

    queryParameters = request.args
    print(queryParameters['fieldKey'])

    query = "SELECT LAST(" + lookupQueryParameterToInflux.get(queryParameters['fieldKey']) + "), ID FROM airQuality GROUP BY ID"

    data = influxClientPolling.query(query, epoch=None)
    data = data.raw

    dataSeries = list(map(lambda x: dict(zip(x['columns'], x['values'][0])), data['series']))

    lastValueObject = {aSensor["ID"]: aSensor for aSensor in dataSeries}

    return jsonify(lastValueObject)


# HELPER FUNCTIONS

def createSelection(typeOfQuery, querystring):
    """Creates the selection string for the SELECT statement."""

    if typeOfQuery == 'raw':

        # db = querystring['sensorSource']

        show = querystring['show'].split(',')

        # if db != 'AirU':
        # create the selection string
        if 'all' in show:
            selectString = "*"
        else:
            selectString = 'ID'
            for aShow in show:
                showExists = lookupQueryParameterToInflux.get(aShow)

                if aShow != 'id' and showExists is not None:
                    selectString = selectString + ", " + showExists
        # else:
        #     # AirU
            # if 'all' in show:
    elif typeOfQuery == 'processed':
        argument = querystring['functionArg']
        argumentExists = lookupQueryParameterToInflux.get(argument)

        if argumentExists is not None:
            selectString = querystring['function'] + "(" + argumentExists + ")"

    return selectString


def getAllCurrentlyLiveAirUs():

    mongodb_url = 'mongodb://{user}:{password}@{host}:{port}/{database}'.format(
        user=current_app.config['MONGO_USER'],
        password=current_app.config['MONGO_PASSWORD'],
        host=current_app.config['MONGO_HOST'],
        port=current_app.config['MONGO_PORT'],
        database=current_app.config['MONGO_DATABASE'])

    mongoClient = MongoClient(mongodb_url)
    db = mongoClient.airudb
    liveAirUs = []

    for aSensor in db.sensors.find():
        liveAirUs.append({'mac': ''.join(aSensor['sensor_mac'].split(':')), 'registeredAt': aSensor['created_at']})

    return liveAirUs


# https://stackoverflow.com/questions/38987/how-to-merge-two-dictionaries-in-a-single-expression
def mergeTwoDicts(x, y):
    z = x.copy()   # start with x's keys and values
    z.update(y)    # modifies z with y's keys and values & returns None
    return z
