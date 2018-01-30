"""Test the config manager."""
import asyncio
from unittest.mock import MagicMock, patch, mock_open

import pytest

from homeassistant import config_manager, loader
from homeassistant.setup import async_setup_component

from tests.common import MockModule, mock_coro, MockConfigEntry


@pytest.fixture
def manager(hass):
    """Fixture of a loaded config manager."""
    manager = config_manager.ConfigManager(MagicMock())
    manager.entries = []
    return manager


@asyncio.coroutine
def test_call_setup_config_entry(hass):
    """Test we call setup_config_entry."""
    MockConfigEntry(domain='comp').add_to_hass(hass)

    mock_setup_entry = MagicMock(return_value=mock_coro(True))

    loader.set_component(
        'comp',
        MockModule('comp', async_setup_entry=mock_setup_entry))

    result = yield from async_setup_component(hass, 'comp', {})
    assert result
    assert len(mock_setup_entry.mock_calls) == 1


@asyncio.coroutine
def test_configure_reuses_handler_instance(manager):
    """Test that we reuse instances."""
    class TestFlow(config_manager.ConfigFlowHandler):
        handle_count = 0

        @asyncio.coroutine
        def async_step_init(self, user_input=None):
            self.handle_count += 1
            return self.async_show_form(
                title='title',
                step_id=str(self.handle_count))

    with patch('homeassistant.config_manager.HANDLERS.get',
               return_value=TestFlow):
        form = yield from manager.async_configure('test')
        assert form['step_id'] == '1'
        form = yield from manager.async_configure('test', form['flow_id'])
        assert form['step_id'] == '2'
        assert len(manager.progress) == 1
        assert len(manager.entries) == 0


@asyncio.coroutine
def test_configure_two_steps(manager):
    """Test that we reuse instances."""
    class TestFlow(config_manager.ConfigFlowHandler):
        @asyncio.coroutine
        def async_step_init(self, user_input=None):
            if user_input is not None:
                self.init_data = user_input
                return self.async_step_second()
            return self.async_show_form(
                title='title',
                step_id='init'
            )

        @asyncio.coroutine
        def async_step_second(self, user_input=None):
            if user_input is not None:
                return self.async_create_entry(
                    title='Test Entry',
                    data=self.init_data + user_input
                )
            return self.async_show_form(
                title='title',
                step_id='second'
            )

    with patch('homeassistant.config_manager.HANDLERS.get',
               return_value=TestFlow):
        form = yield from manager.async_configure('test')
        form = yield from manager.async_configure(
            'test', form['flow_id'], form['step_id'], ['INIT-DATA'])
        form = yield from manager.async_configure(
            'test', form['flow_id'], form['step_id'], ['SECOND-DATA'])
        assert form['type'] == config_manager.RESULT_TYPE_CREATE_ENTRY
        assert len(manager.progress) == 0
        assert len(manager.entries) == 1
        entry = manager.entries[0]
        assert entry.domain == 'test'
        assert entry.data == ['INIT-DATA', 'SECOND-DATA']


@asyncio.coroutine
def test_abort_removes_instance(manager):
    """Test that abort removes the flow from progress."""
    class TestFlow(config_manager.ConfigFlowHandler):
        is_new = True

        @asyncio.coroutine
        def async_step_init(self, user_input=None):
            old = self.is_new
            self.is_new = False
            return self.async_abort(reason=str(old))

    with patch('homeassistant.config_manager.HANDLERS.get',
               return_value=TestFlow):
        form = yield from manager.async_configure('test')
        assert form['reason'] == 'True'
        form = yield from manager.async_configure('test', form['flow_id'])
        assert form['reason'] == 'True'
        assert len(manager.progress) == 0
        assert len(manager.entries) == 0


@asyncio.coroutine
def test_create_saves_data(manager):
    """Test creating a config entry."""
    class TestFlow(config_manager.ConfigFlowHandler):
        version = 5

        @asyncio.coroutine
        def async_step_init(self, user_input=None):
            return self.async_create_entry(
                title='Test Title',
                data='Test Data'
            )

    with patch('homeassistant.config_manager.HANDLERS.get',
               return_value=TestFlow):
        yield from manager.async_configure('test')
        assert len(manager.progress) == 0
        assert len(manager.entries) == 1

        entry = manager.entries[0]
        assert entry.version == 5
        assert entry.domain == 'test'
        assert entry.title == 'Test Title'
        assert entry.data == 'Test Data'
        assert entry.source == config_manager.SOURCE_USER


@asyncio.coroutine
def test_entries_gets_entries(manager):
    MockConfigEntry(domain='test').add_to_manager(manager)
    entry1 = MockConfigEntry(domain='test2')
    entry1.add_to_manager(manager)
    entry2 = MockConfigEntry(domain='test2')
    entry2.add_to_manager(manager)

    assert manager.async_entries('test2') == [entry1, entry2]


@asyncio.coroutine
def test_domains_gets_uniques(manager):
    """Test we only return each domain once."""
    MockConfigEntry(domain='test').add_to_manager(manager)
    MockConfigEntry(domain='test2').add_to_manager(manager)
    MockConfigEntry(domain='test2').add_to_manager(manager)
    MockConfigEntry(domain='test').add_to_manager(manager)
    MockConfigEntry(domain='test3').add_to_manager(manager)

    assert manager.async_domains() == ['test', 'test2', 'test3']


@asyncio.coroutine
def test_saving_and_loading(hass):
    """Test that we're saving and loading correctly."""
    class TestFlow(config_manager.ConfigFlowHandler):
        version = 5

        @asyncio.coroutine
        def async_step_init(self, user_input=None):
            return self.async_create_entry(
                title='Test Title',
                data={
                    'token': 'abcd'
                }
            )

    with patch('homeassistant.config_manager.HANDLERS.get',
               return_value=TestFlow):
        yield from hass.config_manager.async_configure('test')

    class Test2Flow(config_manager.ConfigFlowHandler):
        version = 3

        @asyncio.coroutine
        def async_step_init(self, user_input=None):
            return self.async_create_entry(
                title='Test 2 Title',
                data={
                    'username': 'bla'
                }
            )

    yaml_path = 'homeassistant.util.yaml.open'

    with patch('homeassistant.config_manager.HANDLERS.get',
               return_value=Test2Flow), \
            patch.object(config_manager, 'SAVE_DELAY', 0):
        yield from hass.config_manager.async_configure('test')

    with patch(yaml_path, mock_open(), create=True) as mock_write:
        yield from asyncio.sleep(0, loop=hass.loop)
        yield from hass.async_block_till_done()

    # Mock open calls are: open file, context enter, write, context leave
    written = mock_write.mock_calls[2][1][0]

    # Now load written data in new config manager
    manager = config_manager.ConfigManager(hass)

    with patch('os.path.isfile', return_value=True), \
            patch(yaml_path, mock_open(read_data=written), create=True):
        yield from manager.async_load()

    # Ensure same order
    for orig, loaded in zip(hass.config_manager.entries, manager.entries):
        assert orig.version == loaded.version
        assert orig.domain == loaded.domain
        assert orig.title == loaded.title
        assert orig.data == loaded.data
        assert orig.source == loaded.source
