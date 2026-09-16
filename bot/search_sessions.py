"""Independent persistent film requests; Telegram replies resolve by message ID."""
import secrets
import time

class SearchSessions:
    TTL = 24 * 3600

    def __init__(self, store, uid):
        self.store, self.uid = store, str(uid)
        self.prefix = 'search-thread:' + self.uid + ':'

    def save(self, state):
        state.setdefault('thread_id', state.get('nonce') or secrets.token_hex(5))
        self.store.write_state(self.prefix + state['thread_id'], state)
        self.store.write_state('search-choice:' + self.uid + ':' + state['nonce'], state['thread_id'])
        self.store.write_state('search:' + self.uid, state)

    def load(self, thread_id):
        state = self.store.read_state(self.prefix + str(thread_id), {})
        return state if state.get('expires', 0) >= time.time() else {}

    def choice(self, nonce):
        thread_id = self.store.read_state('search-choice:' + self.uid + ':' + nonce)
        if thread_id:
            return self.load(thread_id)
        # Preserve the last choice created by the previous installed version.
        state = self.store.read_state('search:' + self.uid, {})
        return state if state.get('nonce') == nonce else {}

    def bind(self, state, message_id):
        if message_id:
            self.store.write_state('search-message:' + self.uid + ':' + str(message_id), state['thread_id'])

    def reply(self, message_id):
        thread_id = self.store.read_state('search-message:' + self.uid + ':' + str(message_id))
        return self.load(thread_id) if thread_id else {}

    def active(self):
        states = self.store.read_states(self.prefix).values()
        return [s for s in states if s.get('expires',0) >= time.time() and s.get('stage') in ('media','release','season')]
