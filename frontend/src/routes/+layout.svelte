<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<script lang="ts">
	import favicon from '#lib/assets/favicon.svg';
	import { ApiError, getMe, logout } from '#lib/api.js';
	import { m } from '#lib/paraglide/messages.js';
	import { getLocale } from '#lib/paraglide/runtime.js';
	import { session } from '#lib/session.svelte.js';
	import LanguageSwitcher from '#lib/LanguageSwitcher.svelte';
	import ThemeSwitcher from '#lib/ThemeSwitcher.svelte';
	import Brand from '#lib/ui/Brand.svelte';
	import Icon from '#lib/ui/Icon.svelte';
	import '#lib/styles/index.css';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	const loginPath = resolve('/login');

	$effect(() => {
		document.documentElement.lang = getLocale();
	});

	$effect(() => {
		getMe()
			.then((user) => (session.user = user))
			.catch((error) => {
				session.user = null;
				if (!(error instanceof ApiError && error.status === 401)) console.error(error);
			})
			.finally(() => (session.checked = true));
	});

	// Every page except the sign-in page needs a signed-in user.
	$effect(() => {
		if (session.checked && !session.user && page.url.pathname !== loginPath) {
			goto(loginPath);
		}
	});

	const pages = $derived([
		{
			href: resolve('/shows'),
			label: m.nav_shows(),
			current: page.route.id?.startsWith('/shows') ?? false
		},
		{ href: resolve('/'), label: m.nav_status(), current: page.route.id === '/' }
	]);

	async function signOut() {
		await logout().catch(() => {});
		session.user = null;
	}
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
	<title>{m.app_title()}</title>
</svelte:head>

<header class="st-header" class:st-header--menu={session.user}>
	<Brand href={session.user ? resolve('/') : undefined} />
	{#if session.user}
		<nav class="st-header__nav">
			{#each pages as item (item.href)}
				<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- resolved above -->
				<a href={item.href} aria-current={item.current ? 'page' : undefined}>{item.label}</a>
			{/each}
		</nav>
	{:else}
		<span class="tagline">{m.app_tagline()}</span>
	{/if}
	<div class="st-header__end">
		{#if session.user}
			<span class="st-header__user st-header__wide">{session.user.name}</span>
			<button type="button" class="st-btn st-btn--ghost st-btn--sm" onclick={signOut}>
				<Icon name="log-out" size={14} />
				{m.auth_sign_out()}
			</button>
		{/if}
		<LanguageSwitcher />
		<ThemeSwitcher />
	</div>
</header>

<main>
	{#if session.checked}
		{@render children()}
	{/if}
</main>

<style>
	.tagline {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	main {
		max-width: 56rem;
		margin: 0 auto;
		padding: var(--space-6);
	}
</style>
