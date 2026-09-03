import assert from 'node:assert/strict';
import test from 'node:test';

import { clearSessionAttachments, setSessionAttachments } from '../src/lib/attachmentState.js';

test('attachment callbacks update only their named session', () => {
	const sessionA = [{ id: 'a-1', displayName: 'a.png' }];
	const sessionB = [{ id: 'b-1', displayName: 'b.txt' }];
	let state = setSessionAttachments({}, 'session-a', sessionA);
	state = setSessionAttachments(state, 'session-b', sessionB);
	state = setSessionAttachments(state, 'session-a', [...sessionA, { id: 'a-2' }]);

	assert.deepEqual(
		state['session-a'].map((attachment) => attachment.id),
		['a-1', 'a-2']
	);
	assert.deepEqual(state['session-b'], sessionB);
	const afterCleanup = clearSessionAttachments(state, 'session-a');
	assert.equal(afterCleanup['session-a'], undefined);
	assert.deepEqual(afterCleanup['session-b'], sessionB);
});
