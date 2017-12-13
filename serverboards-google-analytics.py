#!env/bin/python3

import serverboards, requests, math
import os, json, sys, time, datetime
import httplib2, threading

from serverboards import rpc, print
from oauth2client import client
from urllib.parse import urlencode, urljoin
from googleapiclient import discovery

#DISCOVERY_URI = ('https://analyticsreporting.googleapis.com/$discovery/rest')
OAUTH_AUTH_URL="https://accounts.google.com/o/oauth2/auth"
OAUTH_AUTH_TOKEN_URL="https://accounts.google.com/o/oauth2/token"
OAUTH_AUTH_REVOKE_URL="https://accounts.google.com/o/oauth2/token"

SCOPES = ['https://www.googleapis.com/auth/analytics.readonly']
settings = {}

class ServerboardsStorage(client.Storage):
    def __init__(self, id=None):
        assert id
        self.id=id
        super(ServerboardsStorage, self).__init__(lock=threading.Lock())
    def locked_get(self):
        content = rpc.call("service.get", self.id).get("config", {})
        if not content:
            return None
        try:
            content=json.dumps(content)
            credentials = client.OAuth2Credentials.from_json(content)
            credentials.set_store(self)
            return credentials
        except:
            pass
        return None

    def locked_put(self, credentials):
        data = {"config":json.loads(credentials.to_json())}
        rpc.call("service.update", self.id, data)
    def locked_delete(self):
        rpc.call("service.update", self.id, {"config":{}})

def ensure_settings():
    if "client_id" not in settings:
        data = serverboards.rpc.call("settings.get", "serverboards.google.analytics/settings")
        if not data:
            raise Exception("Google Analytics Integration not configured. Check system settings.")
        settings.update(data)

        base = serverboards.rpc.call("settings.get", "serverboards.core.settings/base")
        settings.update(base)

@serverboards.rpc_method
def authorize_url(service=None, **kwargs):
    if not service:
        return ""
    service_id=service["uuid"]
    ensure_settings()

    params={
        "response_type" : "code",
        "client_id" : settings["client_id"],
        "redirect_uri" : urljoin(settings["base_url"], "/static/serverboards.google.analytics/auth.html"),
        "scope": 'https://www.googleapis.com/auth/analytics.readonly',
        "state": service_id,
        "access_type": "offline",
        "approval_prompt": "force"
    }
    url = OAUTH_AUTH_URL+"?"+urlencode(params)
    return url

@serverboards.rpc_method
def store_code(service_id, code):
    ensure_settings()

    """
    Stores the code and get a refresh token and a access token
    """
    params={
        "code": code,
        "client_id": settings["client_id"],
        "client_secret": settings["client_secret"],
        "redirect_uri": urljoin(settings["base_url"], "/static/serverboards.google.analytics/auth.html"),
        "grant_type": "authorization_code",
    }
    response = requests.post(OAUTH_AUTH_TOKEN_URL, params)
    js = response.json()
    if 'error' in js:
        raise Exception(js['error_description'])
    print(js)
    storage = ServerboardsStorage(service_id)
    credentials = client.OAuth2Credentials(
        access_token=js["access_token"],
        client_id=settings["client_id"],
        client_secret=settings["client_secret"],
        refresh_token=js.get("refresh_token"),
        token_expiry=datetime.datetime.utcnow() + datetime.timedelta(seconds=int(js["expires_in"])),
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

analytics = {}
def get_analytics(service_id, version='v4'):
    ank=(service_id, version)
    if not analytics.get(ank):
        storage = ServerboardsStorage(service_id)
        credentials = storage.get()
        if not credentials:
            raise Exception("Invalid credentials. Reauthorize.")
        analytics[ank] = discovery.build('analytics', version, credentials=credentials)
    return analytics.get(ank)

def date(d,t=0,m=0):
    return time.mktime((int(d[0:4]), int(d[4:6]), int(d[6:8]), int(t), int(m),0, 0,0,0))

def do_clustering(data, start, end, clustering):
    ret=[0.0] * (math.ceil((end-start)/clustering)+1)

    for time, value in data:
        quant = math.ceil((time - start)/clustering)
        if quant >= len(ret):
            serverboards.warning("Trying to add into a out of index quant: %s. max %s"%(quant, len(ret)))
        else:
            ret[quant]+=float(value)

    time=start
    for val in ret:
        yield [time, val]
        time+=clustering

@serverboards.rpc_method
def get_data(service_id, view, start, end):
    analytics = get_analytics(service_id)

    # serverboards.debug("%s %s"%(start, end))
    hour_filter=(
        time.mktime((int(start[0:4]), int(start[5:7]), int(start[8:10]), int(start[11:13]),int(start[14:16]),0, 0,0,0)),
        time.mktime((int(end[0:4]), int(end[5:7]), int(end[8:10]), int(end[11:13]),int(end[14:16]),0, 0,0,0))
    )
    filter_range=hour_filter[1]-hour_filter[0]


    if filter_range > (4*24*60*60):
        extra_dimensions=[]
        clustering=24*60*60
    elif filter_range > (4*60*60):
        extra_dimensions=[{"name":'ga:hour'}]
        clustering=60*60
    elif filter_range > 60*60:
        extra_dimensions=[{"name":'ga:hour'},{"name":'ga:minute'}]
        clustering=15*60
    else:
        extra_dimensions=[{"name":'ga:hour'},{"name":'ga:minute'}]
        clustering=60

    # serverboards.debug("hour filtered %s %s %s %s"%(hour_filter,filter_range, extra_dimensions, clustering))

    data = analytics.reports().batchGet(
          body={
            'reportRequests': [
            {
              'viewId': view,
              'dateRanges': [{'startDate': start[0:10], 'endDate': end[0:10]}],
              'metrics': [{'expression': 'ga:sessions'}],
              'dimensions': [{"name":'ga:date'}] + extra_dimensions
            }]
          }
      ).execute()

    def decorate(datum):
        d=date(*datum['dimensions'])
        # serverboards.debug("%s %s %s %s"%(datum, d, hour_filter, hour_filter[0] <= d <= hour_filter[1]))
        if not (hour_filter[0] <= d <= hour_filter[1]):
             return None
        return [d, datum['metrics'][0]['values'][0]]
    # serverboards.debug("Result: %s"%(data,))

    data = [decorate(x) for x in data['reports'][0]['data'].get('rows',[])]
    data = [x for x in data if x] # remove empty
    data = list( do_clustering(data, *hour_filter, clustering) )

    name = get_view_name(service_id, view) + " - " + "Sessions"
    # serverboards.debug("Return data %s"%(data,))

    return [{"name": name, "values" : data}]

@serverboards.rpc_method
def get_view_name(service_id, viewid):
    try:
        return next(x for x in get_views(service_id) if x["value"]==viewid)["name"]
    except:
        raise Exception("View not found")

views_cache=None
@serverboards.rpc_method
def get_views(service=None, **kwargs):
    global views_cache
    if views_cache:
        return views_cache
    analytics = get_analytics(service, 'v3')
    accounts = analytics.management().accountSummaries().list().execute()
    accounts = [
            {
                "name":"%s - %s"%(p['name'], pp['name']),
                "value": pp["id"]
            }
        for a in accounts['items']
        for p in a['webProperties']
        for pp in p['profiles']
        ]
    accounts.sort(key=lambda ac: ac['name'])
    views_cache=accounts
    return accounts

@serverboards.rpc_method
def check_rules(*_args, **_kwargs):
    rules = serverboards.rpc.call("rules.list", trigger="serverboards.google.analytics/trigger", is_active=True)
    for r in rules:
        params = r["trigger"]["params"]
        service_id = params["service"]["uuid"]
        view = params["viewid"]
        end = datetime.datetime.now().strftime("%Y-%m-%d")
        state = False
        limit = float(params["value"])
        cond = params["condition"] or ">"
        data = get_data(service_id, view, end, end)
        value = float(data[0]["values"][0][1])

        if cond == "<":
            state = value < limit
        elif cond == "<=":
            state = value <= limit
        elif cond == ">":
            state = value > limit
        elif cond == ">=":
            state = value >= limit
        state = "ok" if state else "nok"
        serverboards.info("Google Analytics Rule check %s: %s %s %s -> %s"%(r["uuid"], value, cond, limit, state))
        serverboards.rpc.event("rules.trigger", id=r["uuid"], state=state, value=value)

def test():
    aurl = authorize_url()
    assert aurl
    #analytics = connect_to_analytics()
    #assert analytics


    print("Success")

if __name__=='__main__':
    if len(sys.argv)==2 and sys.argv[1]=='test':
        test()
    else:
        serverboards.loop()
