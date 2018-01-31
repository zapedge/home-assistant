"""Helper to manage entering configuration."""
import asyncio
import os
import uuid

from .core import callback
from .exceptions import HomeAssistantError
from .util.decorator import Registry
from .util.json import load_json, save_json


SOURCE_USER = 'user'
SOURCE_DISCOVERY = 'discovery'

HANDLERS = Registry()
PATH_CONFIG = '.config_manager.json'

DATA_CONFIG_MANAGER = 'config_manager'
SAVE_DELAY = 1

RESULT_TYPE_FORM = 'form'
RESULT_TYPE_CREATE_ENTRY = 'create_entry'
RESULT_TYPE_ABORT = 'abort'
# RESULT_TYPE_LOADING = 'loading' (auto refresh in 1 seconds)

# Future
# Allow strategies. Like max 1 account allowed,


class ConfigEntry:
    """Hold a configuration entry."""

    __slots__ = ('config_id', 'version', 'domain', 'title', 'data', 'source')

    def __init__(self, config_id, version, domain, title, data, source):
        """Initialize a config entry."""
        # Unique id of the config entry
        self.config_id = config_id

        # Version of the configuration.
        self.version = version

        # Domain the configuration belongs to
        self.domain = domain

        # Title of the configuration
        self.title = title

        # Config data
        self.data = data

        # Source of the configuration (user, discovery, cloud)
        self.source = source

    def as_dict(self):
        """Return dictionary version of this entry."""
        return {
            'config_id': self.config_id,
            'version': self.version,
            'domain': self.domain,
            'title': self.title,
            'data': self.data,
            'source': self.source,
        }


class ConfigError(HomeAssistantError):
    """Error while configuring an account."""


class UnknownHandler(ConfigError):
    """Unknown handler specified."""


class UnknownStep(ConfigError):
    """Unknown step specified."""


class ConfigManager:
    """Manage the configurations and keep track of the ones in progress."""

    def __init__(self, hass):
        """Initialize the config manager."""
        self.hass = hass
        self.entries = None
        self.progress = {}
        self._sched_save = None

    def async_domains(self):
        """Return domains for which we have entries."""
        seen = set()
        result = []

        for entry in self.entries:
            if entry.domain not in seen:
                seen.add(entry.domain)
                result.append(entry.domain)

        return result

    def async_entries(self, domain):
        """Return all entries for a specific domain."""
        return [entry for entry in self.entries if entry.domain == domain]

    def async_configure(self, domain, flow_id=None, step_id='init',
                        user_input=None):
        """Start or continue a configuration flow."""
        handler = HANDLERS.get(domain)

        if handler is None:
            # TODO: see if we can load component (and install requirements)
            raise UnknownHandler

        flow = None

        if flow_id is not None:
            flow = self.progress.get(flow_id)

        if flow is None:
            flow_id = uuid.uuid4().hex
            flow = self.progress[flow_id] = handler()
            flow.hass = self.hass
            flow.domain = domain
            flow.flow_id = flow_id

        method = "async_step_{}".format(step_id)

        if not hasattr(flow, method):
            self.progress.pop(flow_id)
            raise UnknownStep("Handler {} doesn't support step {}".format(
                domain, step_id))

        result = yield from getattr(flow, method)(user_input)

        if result['type'] == RESULT_TYPE_FORM:
            return result

        # Abort and Success results finish the flow
        self.progress.pop(flow_id)

        if result['type'] == RESULT_TYPE_ABORT:
            return result

        self.entries.append(ConfigEntry(
            config_id=flow.flow_id,
            version=flow.version,
            domain=domain,
            title=result['title'],
            data=result.pop('data'),
            source=flow.source
        ))
        self.async_schedule_save()
        return result

    @asyncio.coroutine
    def async_load(self):
        """Load the config."""
        assert False
        path = self.hass.config.path(PATH_CONFIG)
        if not os.path.isfile(path):
            self.entries = []

        entries = yield from self.hass.async_add_job(load_json, path)
        self.entries = [ConfigEntry(**entry) for entry in entries]

    @callback
    def async_schedule_save(self):
        """Schedule saving the entity registry."""
        if self._sched_save is not None:
            self._sched_save.cancel()

        self._sched_save = self.hass.loop.call_later(
            SAVE_DELAY, self.hass.async_add_job, self._async_save
        )

    @asyncio.coroutine
    def _async_save(self):
        """Save the entity registry to a file."""
        self._sched_save = None
        data = [entry.as_dict() for entry in self.entries]

        yield from self.hass.async_add_job(
            save_json, self.hass.config.path(PATH_CONFIG), data)


class ConfigFlowHandler:
    """Handle the configuration flow of a component."""

    # Set by config manager
    flow_id = None
    hass = None
    source = SOURCE_USER

    # Set by dev
    version = 0

    @callback
    def async_show_form(self, *, title, step_id, description=None,
                        data_schema=None, errors=None, total_steps=None):
        """Return a form to show."""
        return {
            'type': RESULT_TYPE_FORM,
            'flow_id': self.flow_id,
            'title': title,
            'step_id': step_id,
            'description': description,
            'data_schema': data_schema,
            'errors': errors,
            'total_steps': total_steps
        }

    @callback
    def async_create_entry(self, *, title, data):
        """Finish config handler and create entry."""
        return {
            'type': RESULT_TYPE_CREATE_ENTRY,
            'flow_id': self.flow_id,
            'title': title,
            'data': data,
        }

    @callback
    def async_abort(self, *, reason):
        """Abort the current flow."""
        return {
            'type': RESULT_TYPE_ABORT,
            'flow_id': self.flow_id,
            'reason': reason
        }
