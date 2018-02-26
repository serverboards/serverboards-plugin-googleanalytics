#!env/bin/python3

import serverboards_aio as serverboards
import requests
import math
import json
import sys
import time
import datetime
import curio
import threading

from serverboards_aio import rpc
from oauth2client import client
from urllib.parse import urlencode, urljoin
from googleapiclient import discovery
from pcolor import printc


# DISCOVERY_URI = ('https://analyticsreporting.googleapis.com/$discovery/rest')
OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
OAUTH_AUTH_TOKEN_URL = "https://accounts.google.com/o/oauth2/token"
OAUTH_AUTH_REVOKE_URL = "https://accounts.google.com/o/oauth2/token"

SCOPES = ['https://www.googleapis.com/auth/analytics.readonly']
settings = {}


class ServerboardsStorage(client.Storage):
    def __init__(self, id=None):
        assert id
        self.id = id
        super(ServerboardsStorage, self).__init__()

    def locked_get(self):
        content = (serverboards.async(serverboards.call, "service.get", self.id)
                   .get("config", {}))
        if not content:
            return None
        try:
            content = json.dumps(content)
            credentials = client.OAuth2Credentials.from_json(content)
            credentials.set_store(self)
            return credentials
        except Exception:
            import traceback
            traceback.print_exc()
            printc("Invalid credentials", file=sys.stderr)
            pass
        return None

    def locked_put(self, credentials):
        data = {"config": json.loads(credentials.to_json())}
        serverboards.async(rpc.call, "service.update", self.id, data)

    def locked_delete(self):
        serverboards.async(rpc.call, "service.update", self.id, {"config": {}})


def ensure_settings():
    if "client_id" not in settings:
        data = serverboards.rpc.call(
            "settings.get", "serverboards.google.analytics/settings")
        if not data:
            raise Exception(
                "Google Analytics Integration not configured. \
                 Check system settings.")
        settings.update(data)

        base = serverboards.rpc.call(
            "settings.get", "serverboards.core.settings/base",
            {"base_url": "http://localhost:8080"})
        settings.update(base)


@serverboards.rpc_method
def authorize_url(service=None, **kwargs):
    if not service:
        return ""
    service_id = service["uuid"]
    ensure_settings()

    params = {
        "response_type": "code",
        "client_id": settings["client_id"].strip(),
        "redirect_uri": urljoin(
            settings["base_url"],
            "/static/serverboards.google.analytics/auth.html"),
        "scope": 'https://www.googleapis.com/auth/analytics.readonly',
        "state": service_id,
        "access_type": "offline",
        "approval_prompt": "force"
    }
    url = OAUTH_AUTH_URL + "?" + urlencode(params)
    return url


@serverboards.rpc_method
def store_code(service_id, code):
    ensure_settings()

    """
    Stores the code and get a refresh token and a access token
    """
    params = {
        "code": code,
        "client_id": settings["client_id"].strip(),
        "client_secret": settings["client_secret"].strip(),
        "redirect_uri": urljoin(
            settings["base_url"],
            "/static/serverboards.google.analytics/auth.html"),
        "grant_type": "authorization_code",
    }
    response = requests.post(OAUTH_AUTH_TOKEN_URL, params)
    js = response.json()
    if 'error' in js:
        raise Exception(js['error_description'])
    # printc(js)
    storage = ServerboardsStorage(service_id)
    credentials = client.OAuth2Credentials(
        access_token=js["access_token"],
        client_id=settings["client_id"].strip(),
        client_secret=settings["client_secret"].strip(),
        refresh_token=js.get("refresh_token"),
        token_expiry=datetime.datetime.utcnow(
        ) + datetime.timedelta(seconds=int(js["expires_in"])),
        token_uri=OAUTH_AUTH_TOKEN_URL,
        user_agent=None,
        revoke_uri=OAUTH_AUTH_REVOKE_URL,
        token_response=js,
        scopes=SCOPES,
        token_info_uri="https://www.googleapis.com/oauth2/v3/tokeninfo"
    )
    credentials.set_store(storage)
    storage.put(credentials)

    return "ok"


# @serverboards.cache_ttl(60)
async def get_analytics(service_id, version='v4'):
    """
    This method may block as it uses the
    """
    def threaded():
        storage = ServerboardsStorage(service_id)
        credentials = storage.locked_get()
        if not credentials:
            return None
        analytics = discovery.build(
            'analytics', version, credentials=credentials)
        # printc("Analytics", analytics)
        return analytics
    analytics = await serverboards.sync(threaded)
    # printc("Final analytics: ", analytics)
    return analytics


def date(d, t=0, m=0):
    return time.mktime((int(d[0:4]), int(d[4:6]), int(d[6:8]), int(t), int(m),
                       0, 0, 0, 0))


def do_clustering(data, start, end, clustering):
    ret = [0.0] * (math.ceil((end - start) / clustering) + 1)

    for time_, value in data:
        quant = math.ceil((time_ - start) / clustering)
        if quant >= len(ret):
            serverboards.warning(
                "Trying to add into a out of index quant: %s. max %s" %
                (quant, len(ret)))
        else:
            ret[quant] += float(value)

    time = start
    for val in ret:
        yield [time, val]
        time += clustering


@serverboards.rpc_method
async def get_data(service_id, view, start, end):
    analytics = await get_analytics(service_id)
    assert analytics, "Could not access to analytics of this service"

    # serverboards.debug("%s %s"%(start, end))
    hour_filter = (
        time.mktime((int(start[0:4]), int(start[5:7]), int(
            start[8:10]), int(start[11:13]), int(start[14:16]), 0, 0, 0, 0)),
        time.mktime((int(end[0:4]), int(end[5:7]), int(
            end[8:10]), int(end[11:13]), int(end[14:16]), 0, 0, 0, 0))
    )
    filter_range = hour_filter[1] - hour_filter[0]

    if filter_range > (4 * 24 * 60 * 60):
        extra_dimensions = []
        clustering = 24 * 60 * 60
    elif filter_range > (4 * 60 * 60):
        extra_dimensions = [{"name": 'ga:hour'}]
        clustering = 60 * 60
    elif filter_range > 60 * 60:
        extra_dimensions = [{"name": 'ga:hour'}, {"name": 'ga:minute'}]
        clustering = 15 * 60
    else:
        extra_dimensions = [{"name": 'ga:hour'}, {"name": 'ga:minute'}]
        clustering = 60

    # serverboards.debug("hour filtered %s %s %s %s" %
    #                 (hour_filter,filter_range, extra_dimensions, clustering))

    data = analytics.reports().batchGet(
        body={
            'reportRequests': [
                {
                    'viewId': view,
                    'dateRanges': [{
                        'startDate': start[0:10],
                        'endDate': end[0:10]
                    }],
                    'metrics': [{'expression': 'ga:sessions'}],
                    'dimensions': [{"name": 'ga:date'}] + extra_dimensions
                }]
        }
    ).execute()

    def decorate(datum):
        d = date(*datum['dimensions'])
        # serverboards.debug("%s %s %s %s"%(datum, d, hour_filter,
        #         hour_filter[0] <= d <= hour_filter[1]))
        if not (hour_filter[0] <= d <= hour_filter[1]):
            return None
        return [d, datum['metrics'][0]['values'][0]]
    # serverboards.debug("Result: %s"%(data,))

    data = [decorate(x) for x in data['reports'][0]['data'].get('rows', [])]
    data = [x for x in data if x]  # remove empty
    data = list(do_clustering(data, *hour_filter, clustering))

    name = get_view_name(service_id, view) + " - " + "Sessions"
    # serverboards.debug("Return data %s"%(data,))

    return [{"name": name, "values": data}]


@serverboards.rpc_method
def get_view_name(service_id, viewid):
    try:
        return next(
            x for x in get_views(service_id) if x["value"] == viewid
        )["name"]
    except Exception:
        raise Exception("View not found")


views_cache = None


@serverboards.rpc_method
async def get_views(service_id=None, **kwargs):
    # printc("Get views of ", service_id)
    if not service_id:
        return []
    global views_cache
    if views_cache:
        return views_cache
    analytics = await get_analytics(service_id, 'v3')
    accounts = analytics.management().accountSummaries().list().execute()
    accounts = [
        {
            "name": "%s - %s" % (p['name'], pp['name']),
            "value": pp["id"]
        }
        for a in accounts['items']
        for p in a['webProperties']
        for pp in p['profiles']
    ]
    accounts.sort(key=lambda ac: ac['name'])
    views_cache = accounts
    return accounts


@serverboards.rpc_method
def check_rules(*_args, **_kwargs):
    rules = serverboards.rpc.call(
        "rules.list", trigger="serverboards.google.analytics/trigger",
        is_active=True)
    date = datetime.datetime.now().strftime("%Y-%m-%d")
    for r in rules:
        params = r["trigger"]["params"]
        service_id = params["service_id"]
        view = params["viewid"]
        end = date
        data = get_data(service_id, view, end, end)
        value = float(data[0]["values"][0][1])

        serverboards.info("Google Analytics Rule check %s: %s" %
                          (r["uuid"], value))
        serverboards.rpc.event("rules.trigger", id=r[
                               "uuid"], date=date, value=value)


@serverboards.rpc_method
async def analytics_is_up(service):
    try:
        if await get_analytics(service["uuid"]):
            return "ok"
        else:
            return "nok"
    except Exception:
        return "unauthorized"


ACCOUNT_COLUMNS = [
    "account_id", "account_name",
    "property_id", "property_name", "property_url",
    "profile_id", "profile_name"
]

DATA_COLUMNS = [
    "profile_id",
    "datetime",
    "source", "medium", "keyword",  # dimensions
    "sessions", "revenue",  # values
]

RT_COLUMNS = [
    "medium", "users"
]


@serverboards.rpc_method
def basic_schema(config, table=None):
    if not table:
        return ["account", "data", "rt"]

    if table == "account":
        return {
            "columns": ACCOUNT_COLUMNS
        }
    if table == "data":
        return {
            "columns": DATA_COLUMNS
        }
    if table == "rt":
        return {
            "columns": RT_COLUMNS
        }
    raise Exception("unknown-table")


@serverboards.rpc_method
async def basic_extractor(config, table, quals, columns):
    # printc("At basic extractor", color="yellow")
    if table == "account":
        return await basic_extractor_accounts(config, quals, columns)
    if table == "data":
        return await basic_extractor_data(config, quals, columns)
    if table == "rt":
        return await rt_extractor(config, quals, columns)
    raise Exception("unknown-table")


# @serverboards.cache_ttl(60)
async def basic_extractor_accounts(config, quals, columns):
    service_id = config["service"]

    analytics = await get_analytics(service_id, 'v3')
    # printc("Analytics", analytics, color="green")
    assert analytics, "Invalid analytics"
    accounts = await serverboards.sync(
        lambda: analytics.management().accountSummaries().list().execute()
    )
    rows = [
        [
            account["id"],
            account["name"],
            prop["id"],
            prop["name"],
            prop.get("websiteUrl"),
            profile["id"],
            profile["name"],
        ]
        for account in accounts['items']
        for prop in account['webProperties']
        for profile in prop['profiles']
    ]

    return {
        "columns": ACCOUNT_COLUMNS,
        "rows": rows
    }


async def basic_extractor_data(config, quals, columns):
    # printc(config)
    service_id = config["service"]
    profile_id = (
        config.get("config", {}).get("viewid") or
        get_qual(quals, "=", "profile_id")
    )
    start = get_qual(quals, ">=", "datetime")[:10]
    end = get_qual(quals, "<=", "datetime")[:10]

    return await basic_extractor_data_cacheable(
        start, end, service_id, profile_id, columns
    )


# @serverboards.cache_ttl(120)
async def basic_extractor_data_cacheable(start, end, service_id,
                                         profile_id, columns):
    for c in columns:
        if c not in DATA_COLUMNS:
            raise Exception("unknown-column %s" % c)

    analytics = await get_analytics(service_id, 'v4')
    days = day_diff(end, start)
    rcolumns = ["profile_id", "datetime"]

    extra_dimensions = []
    datetime_size = 1
    if days <= 3:
        extra_dimensions.append({"name": 'ga:hour'})
        datetime_size += 1
    if days <= 1:
        extra_dimensions.append({"name": 'ga:minute'})
        datetime_size += 1

    if 'source' in columns:
        extra_dimensions.append({"name": "ga:source"})
        rcolumns.append("source")
    if 'medium' in columns:
        extra_dimensions.append({"name": "ga:medium"})
        rcolumns.append("medium")
    if 'keyword' in columns:
        extra_dimensions.append({"name": "ga:keyword"})
        rcolumns.append("keyword")

    metrics = []
    if 'sessions' in columns:
        metrics.append({'expression': 'ga:sessions'})
        rcolumns.append("sessions")
    if 'revenue' in columns:
        metrics.append({'expression': 'ga:transactionRevenue'})
        rcolumns.append("revenue")

    rows = []
    data = await serverboards.sync(
        lambda:
        analytics.reports().batchGet(
            body={
                'reportRequests': [
                    {
                        'viewId': profile_id,
                        'dateRanges': [{
                            'startDate': start,
                            'endDate': end
                        }],
                        'metrics': metrics,
                        'dimensions': [{"name": 'ga:date'}] + extra_dimensions
                    }]
            }
        ).execute()
    )
    for dm in data["reports"][0]["data"]["rows"]:
        time_ = dim_to_datetime(*(dm["dimensions"][:datetime_size]))
        dimensions = dm["dimensions"][datetime_size:]
        values = dm["metrics"][0]["values"]
        rows.append([
            profile_id, time_, *dimensions, *values
        ])

    return {
        "columns": rcolumns,
        "rows": rows
    }


async def rt_extractor(config, quals, columns):
    service_id = config["service"]
    profile_id = (
        config.get("config", {}).get("viewid") or
        get_qual(quals, "=", "profile_id")
    )
    analytics = await get_analytics(service_id, 'v3')

    retcols = []
    dimensions = []
    if 'medium' in columns:
        dimensions.append("rt:medium")
        retcols.append("medium")

    if dimensions:
        dimensions = ','.join(dimensions)
    else:
        dimensions = None

    retcols.append("users")

    res = analytics.data().realtime().get(
        ids='ga:%s' % profile_id,
        metrics='rt:activeUsers',
        dimensions=dimensions).execute()
    # printc(json.dumps(res, indent=2))
    rows = res.get("rows", [])

    return {
        "columns": retcols,
        "rows": rows
    }


def day_diff(end, start):
    endd = datetime.date(int(end[:4]), int(end[5:7]), int(end[8:10]))
    startd = datetime.date(int(start[:4]), int(start[5:7]), int(start[8:10]))
    return (endd - startd).days


def dim_to_datetime(date, hour="00", minute="00"):
    return "%s-%s-%sT%s:%s" % \
        (date[:4], date[4:6], date[6:8], hour, minute)


def get_qual(quals, op, column, default=None):
    for q in quals:
        if q[0] == column and q[1] == op:
            return q[2]
    return default


async def test():
    sys.stdout = sys.stderr
    # from smock import mock_method_async
    import yaml
    mock_data = yaml.load(open("mock.yaml"))
    printc("Start tests", color="blue")

    serverboards.test_mode(mock_data=mock_data)
    try:

        tables = basic_schema({})
        assert tables != []

        data = basic_schema({}, "data")
        assert data != []
        data = basic_schema({}, "rt")
        assert data != []
        data = basic_schema({}, "account")
        assert data != []

        config = {
            "service": "XXX"
        }
        printc("Get accounts")
        accounts = await basic_extractor(
            config, "account", [], ACCOUNT_COLUMNS)
        printc("acc", accounts, color="blue")

        data = await basic_extractor(
            config, "data", [("profile_id", "=", "102828992"), ("datetime", ">=", "2017-01-01"), ("datetime", "<=", "2017-01-31")], DATA_COLUMNS)
        printc("data", data, color="blue")

        printc("Success", color="green")
        sys.exit(0)
    except SystemExit:
        raise
    except curio.TaskCancelled as tc:
        print(tc)
        printc("\n\nFailed\n", color="red")
    except Exception:
        printc("\n\nFailed\n", color="red")
        import traceback
        traceback.print_exc()
        await curio.sleep(1)


if __name__ == '__main__':
    if len(sys.argv) == 2 and sys.argv[1] == '--test':
        serverboards.run_async(curio.spawn, test)
        serverboards.rpc.stdin = None
        serverboards.loop(debug=curio.debug.schedtrace, with_monitor=True)
        printc("Failed!")
        sys.exit(1)
    else:
        serverboards.loop()
