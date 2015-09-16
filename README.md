App Engine application for the Udacity training course.

## Products
- [App Engine][1]

## Language
- [Python][2]

## APIs
- [Google Cloud Endpoints][3]

## Setup Instructions
1. Update the value of `application` in `app.yaml` to the app ID you
   have registered in the App Engine admin console and would like to use to host
   your instance of this sample.
1. Update the values at the top of `settings.py` to
   reflect the respective client IDs you have registered in the
   [Developer Console][4].
1. Update the value of CLIENT_ID in `static/js/app.js` to the Web client ID
1. (Optional) Mark the configuration files as unchanged as follows:
   `$ git update-index --assume-unchanged app.yaml settings.py static/js/app.js`
1. Run the app with the devserver using `dev_appserver.py DIR`, and ensure it's running by visiting your local server's address (by default [localhost:8080][5].)
1. (Optional) Generate your client library(ies) with [the endpoints tool][6].
1. Deploy your application.


[1]: https://developers.google.com/appengine
[2]: http://python.org
[3]: https://developers.google.com/appengine/docs/python/endpoints/
[4]: https://console.developers.google.com/
[5]: https://localhost:8080/
[6]: https://developers.google.com/appengine/docs/python/endpoints/endpoints_tool

## Task 1 : Add Session to a Conference

This was implemented using an explicit property 'conference', in this case I found this way to be simpler and clearer. Session class has all the requirements : Session name, highlights, speaker, duration, typeOfSession, startDate and startTime ( 24H format ). I have used various method to fetch data from ndb, I have implemented a classmethod and also explicit code for queries in all the app's endpoints.

    name            = ndb.StringProperty(required=True)
    speaker         = ndb.StringProperty()
    highlights      = ndb.StringProperty(repeated=True)
    duration        = ndb.IntegerProperty()
    typeOfSession   = ndb.StringProperty(choices=['workshop', 'keynotes', 'breakout']) 
    startDate       = ndb.DateProperty()
    startTime       = ndb.TimeProperty()
    conference      = ndb.KeyProperty(kind=r'Conference')

For fields like 'name', 'speaker' and 'highlights' I've used StringProperty() as it will be easier to store and process. I've chosen the 'name' field as required implicitly, we need at least a name for our speaker. Highlights chosen to be repeated can be useful to add more than one highlit to a session. For the 'duration' field have chose IntegerPropery() as a number representing minutes. Type of session has a pre configured list of choices, of course it could be also implemented as a class like in the case of TeeShirtSize. StartDate and StartTime as date and time properties esier to validate. I've added a KeyProperty kind 'Conference' for as a 'To Do' list, it could help build more complex queries only form the Session class itself.

The 'get_session_by_conferencekey' was added to show the use of classmethods which can simplify queries sometime.

   @classmethod
    def get_session_by_conferencekey(cls, confwebsafekey):
        return cls.query(cls.conference == confwebsafekey)

## Task 2 : Add Sessions to User Wishlist

I have added a property to user's profile object : 'sessionWishlist', a repeated string to store every session key, user can also add any session to the interest list regardless if he's registered for the conference or not.
API reference : addSessionToWishlist(SessionKey) - will add a session key and getSessionsInWishlist() will retrieve the entire list of session keys.

## Task 3 : Work on indexes and queries

 I've created two new queries :
 
 - getConferenceSessionsByStartTime - given a conference key and a start time it will return all the session within that conference that are greater or equal to teh start time.

 - getConferenceSessionsByHighlights - this will search in a conference for session that has a highlight of interest

I have added the following indexes to support two new type of queries required :

   - kind: Session
  properties:
  - name: conference
  - name: highlights

- kind: Session
  properties:
  - name: typeOfSession
  - name: startTime

Problem query related problem :
 - the problem in this case is that datastore API does not allow inequality filters on two different properties, as in our case startTime and sessionType.
 - a workaround would be to use datastore to do the query on the first inequality and then post filter the result, as implemented in : getSessionsCustomRequest
 ```

            # first query select all sessions with inequality filter
            sessions_type_filtered = Session.query(Session.typeOfSession != request.excludeSessionType)
            # iterate through the results and look apply second inequality filter
            sessions_qualified = [t for t in sessions_type_filtered if t.startTime >= start_time]
```
## Task 4 : Adding a task

I have added a task to check when a speaker is added if he is also featured in other sessions on the same conference, this will make an entry into the memcache. To check if the memcache had an entry the folowing API can be used which will read the a message containing featured speaker's name : getConferenceSessionsByHighlights
   




 


