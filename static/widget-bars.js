(function(){
  let {BarGraph} = Serverboards.graphs
  let {plugin, store} = Serverboards
  const DATE_FORMAT = "YYYY-MM-DD"

  function main(el, config, context){
    let graph=new BarGraph(el)
    let analytics

    function update(){
      let {start, end} = store.getState().serverboard.daterange
      start=start.format(DATE_FORMAT)
      end=end.format(DATE_FORMAT)

      graph.set_loading()
      analytics.call("get_data", [config.viewid, start, end]).then( (data) => {
        console.log(data)
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
    store.on("serverboard.daterange.start", update)
    store.on("serverboard.daterange.end", update)
  }

  Serverboards.add_widget("serverboards.google.analytics/widget-bars", main)
})()
