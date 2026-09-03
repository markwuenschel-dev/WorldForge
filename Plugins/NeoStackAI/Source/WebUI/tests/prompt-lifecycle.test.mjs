import assert from 'node:assert/strict';
import test from 'node:test';

import { createPromptLifecycleRegistry } from '../src/lib/promptLifecycle.js';

test('prompt is active before delayed acceptance and rejection rolls it back', () => {
	const lifecycle = createPromptLifecycleRegistry();
	lifecycle.beginPrompt('session-a', 'prompt-1');
	assert.equal(lifecycle.isActive('session-a'), true);
	assert.equal(lifecycle.acknowledgePrompt('session-a', 'prompt-1', false), 'rejected');
	assert.equal(lifecycle.isActive('session-a'), false);
});

test('late failures cannot terminate a newer prompt', () => {
	const lifecycle = createPromptLifecycleRegistry();
	lifecycle.beginPrompt('session-a', 'prompt-old');
	lifecycle.beginPrompt('session-a', 'prompt-new');

	assert.equal(lifecycle.acknowledgePrompt('session-a', 'prompt-old', false), 'stale');
	assert.equal(lifecycle.getPromptRequestId('session-a'), 'prompt-new');
	assert.equal(lifecycle.isActive('session-a'), true);
});

test('cancel failure remains retryable and successful acknowledgement finishes only its session', () => {
	const lifecycle = createPromptLifecycleRegistry();
	lifecycle.beginPrompt('session-a', 'prompt-a');
	lifecycle.beginPrompt('session-b', 'prompt-b');

	assert.equal(lifecycle.beginCancellation('session-a', 'cancel-1'), true);
	assert.equal(lifecycle.beginCancellation('session-a', 'cancel-duplicate'), false);
	assert.equal(lifecycle.acknowledgeCancellation('session-a', 'cancel-1', false), 'rejected');
	assert.equal(lifecycle.isActive('session-a'), true);
	assert.equal(lifecycle.beginCancellation('session-a', 'cancel-2'), true);
	assert.equal(lifecycle.acknowledgeCancellation('session-a', 'cancel-2', true), 'accepted');
	assert.equal(lifecycle.isActive('session-a'), false);
	assert.equal(lifecycle.isActive('session-b'), true);
});
