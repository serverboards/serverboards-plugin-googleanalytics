(function(){
  let {BarGraph} = Serverboards.graphs
  let {plugin, store, moment} = Serverboards
  const DATE_FORMAT = "YYYY-MM-DDTHH:mm"
  const MAX_REFRESH_PERIOD_S = 120

  function main(el, config, context){
    let graph=new BarGraph(el)
    let analytics
    graph.set_loading()

    let last_update_timestamp=0
    function update(){
      let current_update_timestamp=moment().unix()
      if (current_update_timestamp - last_update_timestamp < MAX_REFRESH_PERIOD_S)
        return
      last_update_timestamp=current_update_timestamp

      let {start, end} = store.getState().project.daterange


      start=start.format(DATE_FORMAT)
      end=end.format(DATE_FORMAT)

      analytics.call("get_data", [config.service.uuid, config.viewid, start, end]).then( (data) => {
        graph.set_data(data)
        context.setTitle(data[0].name)
      }).catch((e) => {
        if (e=="invalid_grant"){
          console.log(config.service)
          analytics.call("authorize_url", [config.service]).then( (url) => {
            graph.set_error(`Google Drive grant has expired and was not automatically refreshed. Click [here](${url}) to renew.`)
          })
        }
        else
          graph.set_error(e)
      })
    }

    plugin.start("serverboards.google.analytics/daemon")
      .then( function(_analytics){
        analytics=_analytics
      } ).then( update )
    store.on("project.daterange.start", update)
    store.on("project.daterange.end", update)
  }

  Serverboards.add_widget("serverboards.google.analytics/widget-bars", main)
})()
