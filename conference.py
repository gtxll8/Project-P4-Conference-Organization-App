#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'

from datetime import datetime
import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import MultiStringMessage
from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import Session
from models import SessionForm, SessionForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize
from utils import getUserId
from google.appengine.api import memcache
from models import StringMessage
from google.appengine.api import taskqueue


from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
FEATURED_SPEAKER_SESSIONS_KEY = "THIS_IS_A_FEATURED_SPEAKER"
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_POST_REQUEST = endpoints.ResourceContainer(
    SessionForm,
    websafeConferenceKey=messages.StringField(1),
)

SESSION_TYPE_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    sessionType=messages.StringField(2),
)

SPEAKER_SESSIONS_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    speaker=messages.StringField(1),
)

WISHLIST_POST_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeSessionKey=messages.StringField(1),
)

SESSION_START_TIME_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    startTime=messages.StringField(2),
)

SESSION_HIGHLIGHTS_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
    highlights=messages.StringField(2),
)


CUSTOM_SESSION_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    excludeSessionType=messages.StringField(1),
    startTime=messages.StringField(2),
)
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""

# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf

    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )

        return request

    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)

    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)

    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id =  getUserId(user)
        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )

    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q

    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)

    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )

# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf

    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile

    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
            prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)

    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()

    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)

# - - - Registration - - - - - - - - - - - - - - - - - - - -

    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)

    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)

    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)

    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
                      path='conference/{websafeConferenceKey}',
                      http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # Get Conference object from request; bail if not found.
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))

    # - - - Sessions Object- - - - - - - - - - - - - - - - - - -

    def _copySessionToForm(self, session):
        """Copy relevant fields from Session to SessionForm."""
        sf = SessionForm()
        print str(session)
        for field in sf.all_fields():
            if hasattr(session, field.name):
                # convert Date to date string; just copy others
                if field.name in ['startDate', 'startTime'] :
                    setattr(sf, field.name, str(getattr(session, field.name)))
                elif field.name == 'duration':
                    setattr(sf, field.name, int(getattr(session, field.name)))
                else:
                    setattr(sf, field.name, getattr(session, field.name))
        if type(session) is Session:
            # if Session object
            setattr(sf, 'sessionKey', str(session.key.urlsafe()))
        else:
            # if request
            setattr(sf, 'sessionKey', str(session.sessionKey))
        sf.check_initialized()
        return sf

    def _createSessionObject(self, request):
        """Create or update Session object, returning SessionForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")

        # check the user is the owner of the conference
        user_id = getUserId(user)
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the conference organizer can create sessions.')

        # copy SessionForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        data['conference'] = ndb.Key(urlsafe=request.websafeConferenceKey)
        del data['websafeConferenceKey']
        del data['sessionKey']

        # convert dates from strings
        try:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
        except Exception:
            raise ValueError("'startDate' required in this format (year-month-day)")

        try:
            data['startTime'] = datetime.strptime(data['startTime'], '%H:%M').time()
        except Exception:
            raise ValueError("'startTime' needed: '%H:%M' ")

        # check if duration is an integer
        try:
            data['duration'] = int(data['duration'])
        except Exception:
            raise ValueError("'duration' required and has to be a number.")

        # creation of Session and return SessionForm
        new_key = Session(**data).put()
        request.sessionKey = new_key.urlsafe()

        # Check to see if the speaker is present in more than one
        # session and if it is then add a task queue
        speaker_sessions = Session.query(Session.speaker == data['speaker']).count()
        if speaker_sessions > 1:
            taskqueue.add(params={'speaker': data['speaker'],
                          'websafeConferenceKey': request.websafeConferenceKey},
                          url='/tasks/get_featured_speaker'
                          )

        return self._copySessionToForm(request)

    # get all the sessions given a conference
    def _getSessions(self, webSafeKey):
        """Get all sessions from a conference."""
        confkey = ndb.Key(urlsafe=webSafeKey)
        # check if this key belongs to an actual conference
        if not confkey:
            raise endpoints.NotFoundException('No conference found with this key.')

        # retrieve all sessions from ancestor conferences, using
        # an ndb class method actual query is faster
        return Session.get_session_by_conferencekey(confkey)

# - - - Create a session - - - - - - - - - - - - - - - - -

    @endpoints.method(SESSION_POST_REQUEST, SessionForm, path='session/create/{websafeConferenceKey}',
                      http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new session."""
        return self._createSessionObject(request)

# - - - Get all sessions from a given conference - - - - - - - - -

    @endpoints.method(SESSION_GET_REQUEST, SessionForms,
            path='sessions/{websafeConferenceKey}',
            http_method='GET', name='getConferenceSessions')
    def getConferenceSessions(self, request):
        """Given a conference, return all sessions (by websafeConferenceKey)."""
        sessions = self._getSessions(request.websafeConferenceKey).fetch()
        if not sessions:
            return SessionForms(
                items=[]
            )
        # return SessionForm
        return SessionForms(
            items=[self._copySessionToForm(session) for session in sessions]
        )

# - - - - -  Given a conference return a specific session type ( lecture, workshop etc. )- - - -

    @endpoints.method(SESSION_TYPE_GET_REQUEST, SessionForms,
                      path='session/{websafeConferenceKey}/{sessionType}',
                      http_method='GET', name='getConferenceSessionsByType')
    def getConferenceSessionsByType(self, request):
            """Return all sessions of a particular type."""
            all_sessions = self._getSessions(request.websafeConferenceKey)
            type_sessions = all_sessions.filter(Session.typeOfSession ==
                                                request.sessionType)

            return SessionForms(
                items=[self._copySessionToForm(sess) for sess in type_sessions]
            )

# - - - - -  Get all sessions in which a speaker is present- - - -

    @endpoints.method(SPEAKER_SESSIONS_GET_REQUEST, SessionForms,
                      path='session/{speaker}',
                      http_method='GET', name='getSessionsBySpeaker')
    def getSessionsBySpeaker(self, request):
            """Return all sessions featuring a speaker's name."""

            # not using the ndb classmethod this time,
            # select all sessions and filter by speaker
            sessions = Session.query()
            if request.speaker:
                sessions = sessions.filter(Session.speaker == request.speaker)
            return SessionForms(
                items=[self._copySessionToForm(sess) for sess in sessions]
            )

# - - - - -  Add sessions to user wish list - - - - - - - - - -

    @endpoints.method(WISHLIST_POST_REQUEST, MultiStringMessage,
                      path='wishlist/{websafeSessionKey}',
                      http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Adds the session to the current user's wishlist."""

        # check if user is logged in
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()

        # Check if session was already added.
        if request.websafeSessionKey in profile.sessionWishlist:
            raise ConflictException(
                "This session is already on your wishlist.")

        # Add session to wishlist.
        profile.sessionWishlist.append(request.websafeSessionKey)
        profile.put()

        # After adding successfully return the entire wish list
        sessions_list = profile.sessionWishlist

        return MultiStringMessage(data=sessions_list)

# - - - - - Get all the user's whishlist - - - - - - - - - - -

    @endpoints.method(message_types.VoidMessage, MultiStringMessage,
                      http_method='GET', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Get all sessions from the user's wishlist."""

        # check if user is logged in
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()

        # Get all the sessions keys in your wish list
        sessions_list = profile.sessionWishlist

        return MultiStringMessage(data=sessions_list)

# - - - - - - - - - - 2 Extra queries - - - - - - - - - - - - -

    @endpoints.method(SESSION_START_TIME_GET_REQUEST, SessionForms,
                      path='session/{websafeConferenceKey}/by/{startTime}',
                      http_method='GET', name='getConferenceSessionsByStartTime')
    def getConferenceSessionsByStartTime(self, request):
            """Return all sessions for a conference by start time."""

            try:
                start_time = datetime.strptime(request.startTime, '%H:%M').time()

            # if time value is formatted wrongly
            except Exception:
               raise endpoints.BadRequestException("'startTime' needed in this format: '%H:%M' ")

            all_sessions = self._getSessions(request.websafeConferenceKey)
            start_time_sessions = all_sessions.filter(Session.startTime >= start_time)

            return SessionForms(
                items=[self._copySessionToForm(sess) for sess in start_time_sessions]
            )

    @endpoints.method(SESSION_HIGHLIGHTS_GET_REQUEST, SessionForms,
                      path='session/{websafeConferenceKey}/by/{highlights}',
                      http_method='GET', name='getConferenceSessionsByHighlights')
    def getConferenceSessionsByHighlights(self, request):
            """Return all sessions for a conference by start time."""

            all_sessions = self._getSessions(request.websafeConferenceKey)
            start_time_sessions = all_sessions.filter(Session.highlights == request.highlights)

            return SessionForms(
                items=[self._copySessionToForm(sess) for sess in start_time_sessions]
            )

# - - - - - - - - - Non workshop sessions starting after 7PM - - - - - - - - - - - -

    @endpoints.method(CUSTOM_SESSION_GET_REQUEST, SessionForms,
                      path='session/by/{excludeSessionType}/and/{startTime}',
                      http_method='GET', name='getSessionsCustomRequest')
    def getSessionsCustomRequest(self, request):
            """Return all sessions excluding certain type and specific start time"""

            # check time string formatting
            try:
                start_time = datetime.strptime(request.startTime, '%H:%M').time()

            # if time value is formatted wrongly
            except Exception:
                raise endpoints.BadRequestException("'startTime' needed in this format: '%H:%M' ")
            # first query select all sessions with inequality filter
            sessions_type_filtered = Session.query(Session.typeOfSession != request.excludeSessionType)
            # iterate through the results and look apply second inequality filter
            sessions_qualified = [t for t in sessions_type_filtered if t.startTime >= start_time]
            # display results
            return SessionForms(
                items=[self._copySessionToForm(sess) for sess in sessions_qualified]
            )
# - - - - - - - - - Add a task queue when more than one session with same speaker - - - - -

    @staticmethod
    def _getFeaturedSpeaker(speaker, websafeConferenceKey):
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        # get all existing sessions
        all_sessions = Session.get_session_by_conferencekey(websafeConferenceKey)
        # check to see if speaker is present already in other sessions
        speaker_sessions = all_sessions.filter(Session.speaker == speaker)
        if speaker_sessions.count() > 1:
            announcement = '%s %s' % (
                'This speaker is very popular '
                'he is featured in these sessions:',
                ', '.join(sess.name for sess in sessions))
            memcache.set(FEATURED_SPEAKER_SESSIONS_KEY, announcement)
        else:
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(FEATURED_SPEAKER_SESSIONS_KEY)

        return announcement
# - - - - ????????????????????????? - - - - - -
    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/getFeaturedSpeaker',
            http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Return Announcement from memcache."""
        # return an existing announcement from Memcache or an empty string.
        announcement = memcache.get(FEATURED_SPEAKER_SESSIONS_KEY)
        if not announcement:
            announcement = ""
        return StringMessage(data=announcement)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = '%s %s' % (
                'Last chance to attend! The following conferences '
                'are nearly sold out:',
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement

    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        # return an existing announcement from Memcache or an empty string.
        announcement = memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY)
        if not announcement:
            announcement = ""
        return StringMessage(data=announcement)

api = endpoints.api_server([ConferenceApi]) # register API
