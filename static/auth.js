"strict mode";
(function(){
  var LOADING="spinner loading"
  var el
  function setStatus(title, description, icon){
    $(el).find('#title').text(title)
    $(el).find('#description').text(description)

    if (!icon)
      icon=LOADING
    $(el).find('.icon.loading').attr('class',"icon "+icon)
  }

  function main(_el){
    el=_el
    setStatus("Checking code", "Please wait")
    var code = Serverboards.store.getState().routing.locationBeforeTransitions.query.code
    if (!code){
      setStatus("Invalid code", "The received code is invalid. Try to start the process again from the service card.", "red remove")
      return;
    }
    Serverboards.plugin.start("serverboards.google.analytics/daemon").then( function(analytics){
      return analytics.call("store_code", [code])
    }).then( function(){
      setStatus("Code stored", "You can now close this window", "green checkmark")
    }).catch(function(error){
      setStatus("Error storing code", error, "red close")
    })
  }

  Serverboards.add_screen("serverboards.google.analytics/auth", main)
})()
