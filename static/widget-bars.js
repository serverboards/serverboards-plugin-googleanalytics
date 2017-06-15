(function(){
  let {BarGraph} = Serverboards.graphs
  let {plugin, store} = Serverboards
  const DATE_FORMAT = "YYYY-MM-DDTHH:mm"

  function main(el, config, context){
    let graph=new BarGraph(el)
    let analytics
    graph.set_loading()

    function update(){
      let {start, end} = store.getState().project.daterange


      start=start.format(DATE_FORMAT)
      end=end.format(DATE_FORMAT)

      analytics.call("get_data", [config.service.uuid, config.viewid, start, end]).then( (data) => {
        graph.set_data(data)
        context.setTitle(data[0].name)
      }).catch((e) => {
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
