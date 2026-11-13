<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!--
  Sign-in as the Immich user of the app (the one albums are shared with), with its Immich email
  and password, or with an API key for an Immich that signs in only through OAuth.
-->
<script lang="ts">
	import { loginWithKey, loginWithPassword, type Me } from '#lib/api.js';
	import { errorMessage } from '#lib/errors.js';
	import { m } from '#lib/paraglide/messages.js';
	import { session } from '#lib/session.svelte.js';
	import Brand from '#lib/ui/Brand.svelte';
	import Icon from '#lib/ui/Icon.svelte';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';

	let email = $state('');
	let password = $state('');
	let apiKey = $state('');
	let busy = $state(false);
	let error = $state<string | null>(null);

	async function signIn(event: SubmitEvent, request: () => Promise<Me>) {
		event.preventDefault();
		busy = true;
		error = null;
		try {
			session.user = await request();
			password = '';
			apiKey = '';
			await goto(resolve('/'));
		} catch (e) {
			error = errorMessage(e);
		} finally {
			busy = false;
		}
	}
</script>

<div class="login">
	<div class="card">
		<Brand large />
		<h1>{m.auth_heading()}</h1>
		<p class="intro">{m.auth_intro()}</p>

		{#if error}
			<div class="st-banner st-banner--danger" role="alert">
				<Icon name="circle-alert" />
				<span class="st-banner__body">{error}</span>
			</div>
		{/if}

		<form onsubmit={(e) => signIn(e, () => loginWithPassword(email, password))}>
			<label class="st-field">
				<span class="st-field__label">{m.auth_email()}</span>
				<input type="email" bind:value={email} autocomplete="username" required disabled={busy} />
			</label>
			<label class="st-field">
				<span class="st-field__label">{m.auth_password()}</span>
				<input
					type="password"
					bind:value={password}
					autocomplete="current-password"
					required
					disabled={busy}
				/>
			</label>
			<button type="submit" class="st-btn st-btn--primary" disabled={busy}>
				{m.auth_sign_in()}
			</button>
			<p class="hint">{m.auth_password_hint()}</p>
		</form>

		<details>
			<summary>{m.auth_with_key()}</summary>
			<form onsubmit={(e) => signIn(e, () => loginWithKey(apiKey))}>
				<label class="st-field">
					<span class="st-field__label">{m.auth_api_key()}</span>
					<input type="password" bind:value={apiKey} autocomplete="off" required disabled={busy} />
				</label>
				<button type="submit" class="st-btn" disabled={busy}>{m.auth_sign_in()}</button>
				<p class="hint">{m.auth_key_hint()}</p>
			</form>
		</details>
	</div>
</div>

<style>
	.login {
		display: grid;
		place-items: center;
		min-height: 70vh;
	}
	.card {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		width: min(26rem, 100%);
		padding: var(--space-8) var(--space-6);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface);
		box-shadow: var(--shadow-md);
	}
	h1 {
		margin: var(--space-2) 0 0;
		font-size: var(--text-xl);
	}
	.intro,
	.hint {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	form {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	details summary {
		cursor: pointer;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	details form {
		margin-top: var(--space-3);
	}
</style>
