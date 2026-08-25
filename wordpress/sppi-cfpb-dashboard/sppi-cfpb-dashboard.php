<?php
/**
 * Plugin Name:       SPPI CFPB Complaint Dashboard
 * Description:       Renders the Southwest Public Policy Institute's CFPB complaint-database dashboard from a published JSON feed. Use the [sppi_cfpb_dashboard] shortcode.
 * Version:           1.1.0
 * Requires at least: 6.0
 * Tested up to:      6.8
 * Requires PHP:      7.4
 * Author:            Southwest Public Policy Institute
 * License:           GPL-2.0-or-later
 * Text Domain:       sppi-cfpb-dashboard
 * Update URI:        https://southwestpolicy.github.io/cfpb-complaint-dashboard
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'SPPI_CFPB_VERSION', '1.1.0' );
define( 'SPPI_CFPB_PATH', plugin_dir_path( __FILE__ ) );
define( 'SPPI_CFPB_URL', plugin_dir_url( __FILE__ ) );

/**
 * Where the plugin looks for news of a newer version of itself.
 *
 * Same GitHub Pages site that serves the data, so there is one thing to publish
 * and one host to trust rather than two. See the updater at the foot of this
 * file for what is expected to be there.
 */
define( 'SPPI_CFPB_UPDATE_MANIFEST', 'https://southwestpolicy.github.io/cfpb-complaint-dashboard/plugin/update.json' );

/**
 * Default location of the published payload.
 *
 * A real, working URL rather than a placeholder: a placeholder means a fresh
 * install fails silently until someone notices the setting, which is exactly
 * what happened the first time this shipped. Override under
 * Settings -> CFPB Dashboard if the feed ever moves.
 */
define( 'SPPI_CFPB_DEFAULT_FEED', 'https://southwestpolicy.github.io/cfpb-complaint-dashboard/data/dashboard.json' );

/** How long a successful fetch is cached. The upstream file changes monthly. */
define( 'SPPI_CFPB_TTL', 12 * HOUR_IN_SECONDS );

/**
 * The feed URL, filterable for staging environments.
 */
function sppi_cfpb_feed_url() {
	$url = get_option( 'sppi_cfpb_feed_url', SPPI_CFPB_DEFAULT_FEED );
	return apply_filters( 'sppi_cfpb_feed_url', $url );
}

/**
 * Fetch and cache the payload.
 *
 * Fetching server-side rather than from the browser avoids a cross-origin
 * request, keeps the page rendering when the upstream host is unavailable, and
 * means the data is present in the HTML for anything that does not run
 * JavaScript. The last good copy is retained separately so an upstream failure
 * degrades to stale data rather than an empty panel.
 *
 * @param bool $force Bypass the cache.
 * @return array{data:array|null,stale:bool,error:string}
 */
function sppi_cfpb_get_data( $force = false ) {
	$cached = get_transient( 'sppi_cfpb_data' );
	if ( ! $force && is_array( $cached ) ) {
		return array( 'data' => $cached, 'stale' => false, 'error' => '' );
	}

	$response = wp_remote_get(
		sppi_cfpb_feed_url(),
		array(
			'timeout'    => 15,
			'user-agent' => 'SPPI-CFPB-Dashboard/' . SPPI_CFPB_VERSION . '; ' . home_url(),
		)
	);

	$error = '';
	if ( is_wp_error( $response ) ) {
		$error = $response->get_error_message();
	} elseif ( 200 !== (int) wp_remote_retrieve_response_code( $response ) ) {
		$error = 'HTTP ' . wp_remote_retrieve_response_code( $response );
	} else {
		$decoded = json_decode( wp_remote_retrieve_body( $response ), true );
		if ( is_array( $decoded ) && isset( $decoded['headline'] ) ) {
			set_transient( 'sppi_cfpb_data', $decoded, SPPI_CFPB_TTL );
			update_option( 'sppi_cfpb_last_good', $decoded, false );
			return array( 'data' => $decoded, 'stale' => false, 'error' => '' );
		}
		$error = 'malformed payload';
	}

	$fallback = get_option( 'sppi_cfpb_last_good' );
	if ( is_array( $fallback ) ) {
		return array( 'data' => $fallback, 'stale' => true, 'error' => $error );
	}
	return array( 'data' => null, 'stale' => false, 'error' => $error );
}

/**
 * Map the shortcode's alignment to the theme's own class.
 *
 * WordPress themes already have a vocabulary for this — `alignwide` and
 * `alignfull` are what the block editor emits and what every modern theme
 * styles — so the dashboard borrows it instead of inventing widths. In Twenty
 * Twenty that means 120rem for wide against 58rem for ordinary content, and a
 * theme with different measures gets its own without this plugin knowing them.
 *
 * @param string $align One of wide, full, none.
 * @return string Class to add to the wrapper, or ''.
 */
function sppi_cfpb_align_class( $align ) {
	switch ( strtolower( trim( $align ) ) ) {
		case 'full':
			return 'alignfull';
		case 'none':
		case '':
			return '';
		default:
			return 'alignwide';
	}
}

/**
 * Tell page caches not to store this render.
 *
 * The failure and stale branches are transient by nature. A page cache that
 * captures one freezes it for every anonymous visitor until something else
 * invalidates the entry, which turns a few seconds of upstream trouble into an
 * apparently permanent outage — with no sign of it for a logged-in editor,
 * whose requests bypass the cache. `DONOTCACHEPAGE` is the constant WP-Optimize,
 * WP Super Cache, W3 Total Cache and LiteSpeed all honour.
 */
function sppi_cfpb_do_not_cache() {
	if ( ! defined( 'DONOTCACHEPAGE' ) ) {
		define( 'DONOTCACHEPAGE', true );
	}
}

/**
 * Shortcode: [sppi_cfpb_dashboard panels="..." align="wide" heading="h2"]
 *
 * panels  Which panels to show, in order.
 * align   wide (default) | full | none. Charts, the map and tables want more
 *         room than a text column; prose inside stays at the theme's reading
 *         measure regardless.
 * heading Level for panel titles. h2 by default so the titles continue the
 *         page outline under the page title rather than skipping a level.
 */
function sppi_cfpb_shortcode( $atts ) {
	$atts = shortcode_atts(
		array(
			'panels'  => 'headline,trend,volume,states,companies,relief',
			'align'   => 'wide',
			'heading' => 'h2',
		),
		$atts,
		'sppi_cfpb_dashboard'
	);

	$align_class = sppi_cfpb_align_class( $atts['align'] );
	$heading     = preg_match( '/^h[1-6]$/i', trim( $atts['heading'] ) )
		? strtolower( trim( $atts['heading'] ) )
		: 'h2';

	$result = sppi_cfpb_get_data();
	if ( null === $result['data'] ) {
		sppi_cfpb_do_not_cache();
		$out = '<div class="sppi-cfpb sppi-cfpb-error"><p>'
			. esc_html__( 'The complaint dashboard is temporarily unavailable.', 'sppi-cfpb-dashboard' )
			. '</p>';

		// Administrators get the actual reason and the URL that was tried.
		// Without this the only symptom is the sentence above, which does not
		// distinguish a wrong URL from a host that blocks outbound requests.
		if ( current_user_can( 'manage_options' ) ) {
			$out .= '<p><small>'
				. esc_html__( 'Visible to administrators only —', 'sppi-cfpb-dashboard' ) . ' '
				. esc_html__( 'fetch failed:', 'sppi-cfpb-dashboard' ) . ' <code>'
				. esc_html( $result['error'] ? $result['error'] : 'unknown' )
				. '</code><br>' . esc_html__( 'URL tried:', 'sppi-cfpb-dashboard' ) . ' <code>'
				. esc_html( sppi_cfpb_feed_url() ) . '</code><br>'
				. '<a href="' . esc_url( admin_url( 'options-general.php?page=sppi-cfpb-dashboard' ) ) . '">'
				. esc_html__( 'Check the dashboard settings', 'sppi-cfpb-dashboard' )
				. '</a></small></p>';
		}
		return $out . '</div>';
	}

	wp_enqueue_style(
		'sppi-cfpb',
		SPPI_CFPB_URL . 'assets/dashboard.css',
		array(),
		SPPI_CFPB_VERSION
	);
	wp_enqueue_script(
		'sppi-cfpb',
		SPPI_CFPB_URL . 'assets/dashboard.js',
		array(),
		SPPI_CFPB_VERSION,
		true
	);

	$panels = array_values( array_filter( array_map( 'trim', explode( ',', $atts['panels'] ) ) ) );

	// The payload travels in the page rather than being re-fetched by the
	// browser. wp_add_inline_script keeps it ahead of the renderer.
	wp_add_inline_script(
		'sppi-cfpb',
		'window.SPPI_CFPB = ' . wp_json_encode(
			array(
				'data'    => $result['data'],
				'stale'   => (bool) $result['stale'],
				'panels'  => $panels,
				'heading' => $heading,
				// Served from the plugin's own directory, so the map geometry
				// is same-origin and needs no CORS headers from anywhere.
				'mapUrl'  => SPPI_CFPB_URL . 'assets/us-states.json',
			)
		) . ';',
		'before'
	);

	$through = isset( $result['data']['meta']['data_through'] )
		? $result['data']['meta']['data_through'] : '';

	if ( $result['stale'] ) {
		sppi_cfpb_do_not_cache();
	}

	$classes = trim( 'sppi-cfpb ' . $align_class );

	ob_start();
	?>
	<div class="<?php echo esc_attr( $classes ); ?>"
		data-panels="<?php echo esc_attr( implode( ',', $panels ) ); ?>"
		data-heading="<?php echo esc_attr( $heading ); ?>">
		<div class="sppi-cfpb-mount" role="region"
			aria-label="<?php esc_attr_e( 'CFPB complaint database dashboard', 'sppi-cfpb-dashboard' ); ?>">
			<noscript>
				<p><?php
				printf(
					/* translators: %s: date the data runs through */
					esc_html__( 'This dashboard requires JavaScript. Data runs through %s.', 'sppi-cfpb-dashboard' ),
					esc_html( $through )
				);
				?></p>
			</noscript>
		</div>
		<?php if ( $result['stale'] ) : ?>
			<p class="sppi-cfpb-stale"><?php
			esc_html_e( 'Showing the most recent available figures; the live feed could not be reached.', 'sppi-cfpb-dashboard' );
			?></p>
		<?php endif; ?>
	</div>
	<?php
	return ob_get_clean();
}
add_shortcode( 'sppi_cfpb_dashboard', 'sppi_cfpb_shortcode' );

/* -------------------------------------------------------------------------
 * Settings
 * ---------------------------------------------------------------------- */

function sppi_cfpb_settings_menu() {
	add_options_page(
		__( 'CFPB Dashboard', 'sppi-cfpb-dashboard' ),
		__( 'CFPB Dashboard', 'sppi-cfpb-dashboard' ),
		'manage_options',
		'sppi-cfpb-dashboard',
		'sppi_cfpb_settings_page'
	);
}
add_action( 'admin_menu', 'sppi_cfpb_settings_menu' );

function sppi_cfpb_register_settings() {
	register_setting(
		'sppi_cfpb',
		'sppi_cfpb_feed_url',
		array(
			'type'              => 'string',
			'sanitize_callback' => 'esc_url_raw',
			'default'           => SPPI_CFPB_DEFAULT_FEED,
		)
	);
}
add_action( 'admin_init', 'sppi_cfpb_register_settings' );

function sppi_cfpb_settings_page() {
	if ( ! current_user_can( 'manage_options' ) ) {
		return;
	}

	if ( isset( $_POST['sppi_cfpb_refresh'] ) &&
		check_admin_referer( 'sppi_cfpb_refresh_action', 'sppi_cfpb_refresh_nonce' ) ) {
		delete_transient( 'sppi_cfpb_data' );
		$r = sppi_cfpb_get_data( true );
		echo '<div class="notice notice-' . ( $r['data'] ? 'success' : 'error' ) . '"><p>'
			. ( $r['data']
				? esc_html__( 'Feed refreshed.', 'sppi-cfpb-dashboard' )
				: esc_html__( 'Refresh failed: ', 'sppi-cfpb-dashboard' ) . esc_html( $r['error'] ) )
			. '</p></div>';
	}

	if ( isset( $_POST['sppi_cfpb_update_check'] ) &&
		check_admin_referer( 'sppi_cfpb_update_check_action', 'sppi_cfpb_update_check_nonce' ) ) {
		$m = sppi_cfpb_get_manifest( true );
		// Core caches its own answer separately; without clearing it the
		// Plugins screen would keep showing the previous verdict.
		delete_site_transient( 'update_plugins' );
		echo '<div class="notice notice-' . ( $m ? 'success' : 'error' ) . '"><p>'
			. ( $m
				? esc_html__( 'Update check complete.', 'sppi-cfpb-dashboard' )
				: esc_html__( 'Could not reach the update manifest.', 'sppi-cfpb-dashboard' ) )
			. '</p></div>';
	}

	$result = sppi_cfpb_get_data();
	$meta   = isset( $result['data']['meta'] ) ? $result['data']['meta'] : array();
	?>
	<div class="wrap">
		<h1><?php esc_html_e( 'CFPB Complaint Dashboard', 'sppi-cfpb-dashboard' ); ?></h1>

		<p><?php esc_html_e( 'Place the dashboard on any page or post with this shortcode:', 'sppi-cfpb-dashboard' ); ?>
			<code>[sppi_cfpb_dashboard]</code></p>
		<p><?php esc_html_e( 'To show only some panels:', 'sppi-cfpb-dashboard' ); ?>
			<code>[sppi_cfpb_dashboard panels="headline,trend"]</code></p>
		<p><?php esc_html_e( 'Width. Charts and tables use the theme\'s wide measure by default; "full" spans the viewport, "none" keeps everything in the text column:', 'sppi-cfpb-dashboard' ); ?>
			<code>[sppi_cfpb_dashboard align="wide"]</code></p>
		<p><?php esc_html_e( 'Heading level for panel titles, if h2 does not fit the page outline:', 'sppi-cfpb-dashboard' ); ?>
			<code>[sppi_cfpb_dashboard heading="h3"]</code></p>

		<form method="post" action="options.php">
			<?php settings_fields( 'sppi_cfpb' ); ?>
			<table class="form-table" role="presentation">
				<tr>
					<th scope="row"><label for="sppi_cfpb_feed_url"><?php esc_html_e( 'Data feed URL', 'sppi-cfpb-dashboard' ); ?></label></th>
					<td>
						<input name="sppi_cfpb_feed_url" id="sppi_cfpb_feed_url" type="url"
							class="regular-text code"
							value="<?php echo esc_attr( get_option( 'sppi_cfpb_feed_url', SPPI_CFPB_DEFAULT_FEED ) ); ?>">
						<p class="description"><?php esc_html_e( 'Published by the monthly analysis job. Cached for 12 hours.', 'sppi-cfpb-dashboard' ); ?></p>
					</td>
				</tr>
			</table>
			<?php submit_button(); ?>
		</form>

		<h2><?php esc_html_e( 'Current data', 'sppi-cfpb-dashboard' ); ?></h2>
		<?php if ( $meta ) : ?>
			<table class="widefat striped" style="max-width:640px">
				<tbody>
					<tr><td><?php esc_html_e( 'Data through', 'sppi-cfpb-dashboard' ); ?></td>
						<td><?php echo esc_html( isset( $meta['data_through'] ) ? $meta['data_through'] : '' ); ?></td></tr>
					<tr><td><?php esc_html_e( 'Payload generated', 'sppi-cfpb-dashboard' ); ?></td>
						<td><?php echo esc_html( isset( $meta['generated'] ) ? $meta['generated'] : '' ); ?></td></tr>
					<tr><td><?php esc_html_e( 'Complaints', 'sppi-cfpb-dashboard' ); ?></td>
						<td><?php echo esc_html( number_format_i18n( $result['data']['headline']['complaints'] ) ); ?></td></tr>
					<tr><td><?php esc_html_e( 'Templated share', 'sppi-cfpb-dashboard' ); ?></td>
						<td><?php echo esc_html( $result['data']['headline']['templated_pct'] ); ?>%</td></tr>
				</tbody>
			</table>
		<?php else : ?>
			<p><?php esc_html_e( 'No data cached yet.', 'sppi-cfpb-dashboard' ); ?></p>
		<?php endif; ?>

		<form method="post" style="margin-top:1em">
			<?php wp_nonce_field( 'sppi_cfpb_refresh_action', 'sppi_cfpb_refresh_nonce' ); ?>
			<button class="button" name="sppi_cfpb_refresh" value="1">
				<?php esc_html_e( 'Refresh now', 'sppi-cfpb-dashboard' ); ?>
			</button>
		</form>

		<h2><?php esc_html_e( 'Plugin updates', 'sppi-cfpb-dashboard' ); ?></h2>
		<?php
		$manifest = sppi_cfpb_get_manifest();
		$latest   = $manifest ? $manifest['version'] : '';
		?>
		<p>
			<?php
			printf(
				/* translators: %s: version number */
				esc_html__( 'Installed version: %s', 'sppi-cfpb-dashboard' ),
				'<code>' . esc_html( SPPI_CFPB_VERSION ) . '</code>'
			);
			?>
			<br>
			<?php if ( ! $latest ) : ?>
				<?php esc_html_e( 'Could not reach the update manifest.', 'sppi-cfpb-dashboard' ); ?>
			<?php elseif ( version_compare( $latest, SPPI_CFPB_VERSION, '>' ) ) : ?>
				<?php
				printf(
					/* translators: %s: version number */
					esc_html__( 'Version %s is available.', 'sppi-cfpb-dashboard' ),
					'<strong>' . esc_html( $latest ) . '</strong>'
				);
				?>
				<a href="<?php echo esc_url( admin_url( 'plugins.php' ) ); ?>">
					<?php esc_html_e( 'Update from the Plugins screen', 'sppi-cfpb-dashboard' ); ?></a>
			<?php else : ?>
				<?php esc_html_e( 'This is the current version.', 'sppi-cfpb-dashboard' ); ?>
			<?php endif; ?>
		</p>
		<p class="description">
			<?php
			printf(
				/* translators: %s: manifest URL */
				esc_html__( 'Checked against %s. WordPress also checks on its own roughly twice a day.', 'sppi-cfpb-dashboard' ),
				'<code>' . esc_html( SPPI_CFPB_UPDATE_MANIFEST ) . '</code>'
			);
			?>
		</p>
		<form method="post">
			<?php wp_nonce_field( 'sppi_cfpb_update_check_action', 'sppi_cfpb_update_check_nonce' ); ?>
			<button class="button" name="sppi_cfpb_update_check" value="1">
				<?php esc_html_e( 'Check for updates now', 'sppi-cfpb-dashboard' ); ?>
			</button>
		</form>
	</div>
	<?php
}

/** Clear cached data on deactivation so a reinstall starts clean. */
function sppi_cfpb_deactivate() {
	delete_transient( 'sppi_cfpb_data' );
	delete_transient( 'sppi_cfpb_update' );
}
register_deactivation_hook( __FILE__, 'sppi_cfpb_deactivate' );

/* -------------------------------------------------------------------------
 * Updates
 *
 * This plugin is not on wordpress.org, so nothing tells WordPress that a newer
 * version exists. Rather than a third-party updater library, it uses the
 * mechanism core added in 5.8 for exactly this case: a plugin declaring an
 * `Update URI` header gets its own `update_plugins_{$hostname}` filter, and
 * whatever that filter returns is treated as the authoritative update record.
 * Everything downstream — the notice on the Plugins screen, the update count in
 * the admin menu, one-click update, auto-updates if enabled — is core's, and
 * there is no code here that unpacks or installs anything.
 *
 * What has to exist at the other end is one small JSON file, published by the
 * same GitHub Actions run that publishes the data. Releasing a new version is
 * then: change the version in the header above, push, and every site running
 * the plugin offers the update within twelve hours.
 * ---------------------------------------------------------------------- */

/** Host that may serve both the manifest and the package. */
function sppi_cfpb_update_host() {
	return (string) wp_parse_url( SPPI_CFPB_UPDATE_MANIFEST, PHP_URL_HOST );
}

/**
 * Fetch and validate the update manifest.
 *
 * Cached for six hours because core polls this filter on every update check and
 * on admin page loads that force one. A failed lookup is cached too, briefly —
 * otherwise an unreachable host means a blocking HTTP request on every single
 * admin screen.
 *
 * @param bool $force Bypass the cache.
 * @return array|null Validated manifest, or null.
 */
function sppi_cfpb_get_manifest( $force = false ) {
	if ( ! $force ) {
		$cached = get_transient( 'sppi_cfpb_update' );
		if ( is_array( $cached ) ) {
			return $cached;
		}
		if ( 'none' === $cached ) {
			return null;
		}
	}

	$response = wp_remote_get(
		SPPI_CFPB_UPDATE_MANIFEST,
		array(
			'timeout'    => 10,
			'user-agent' => 'SPPI-CFPB-Dashboard/' . SPPI_CFPB_VERSION . '; ' . home_url(),
		)
	);

	$manifest = null;
	if ( ! is_wp_error( $response ) && 200 === (int) wp_remote_retrieve_response_code( $response ) ) {
		$decoded = json_decode( wp_remote_retrieve_body( $response ), true );
		if ( is_array( $decoded ) && ! empty( $decoded['version'] ) && ! empty( $decoded['download_url'] ) ) {
			// The package must come from the same host as the manifest. Without
			// this, anything that could tamper with the JSON could also point
			// WordPress at an arbitrary zip and have it installed with no
			// further confirmation.
			$host = wp_parse_url( $decoded['download_url'], PHP_URL_HOST );
			if ( $host === sppi_cfpb_update_host() ) {
				$manifest = $decoded;
			}
		}
	}

	set_transient( 'sppi_cfpb_update', null === $manifest ? 'none' : $manifest, 6 * HOUR_IN_SECONDS );
	return $manifest;
}

/**
 * Answer core's update check for this plugin.
 *
 * @param array|false $update      Update offer assembled so far.
 * @param array       $plugin_data Headers from this plugin's file.
 * @param string      $plugin_file Plugin basename.
 * @return array|false
 */
function sppi_cfpb_check_update( $update, $plugin_data, $plugin_file ) {
	// Another handler on the same hostname already answered.
	if ( ! empty( $update ) ) {
		return $update;
	}

	$manifest = sppi_cfpb_get_manifest();
	if ( null === $manifest ) {
		return $update;
	}

	// Only ever offer a move forwards. Reinstalling the current version is what
	// the Plugins screen's own reinstall path is for.
	if ( version_compare( $manifest['version'], SPPI_CFPB_VERSION, '<=' ) ) {
		return $update;
	}

	return array(
		'id'           => sppi_cfpb_update_host() . '/sppi-cfpb-dashboard',
		'slug'         => 'sppi-cfpb-dashboard',
		'plugin'       => $plugin_file,
		'version'      => $manifest['version'],
		'url'          => isset( $manifest['homepage'] ) ? $manifest['homepage'] : '',
		'package'      => $manifest['download_url'],
		'tested'       => isset( $manifest['tested'] ) ? $manifest['tested'] : '',
		'requires'     => isset( $manifest['requires'] ) ? $manifest['requires'] : '',
		'requires_php' => isset( $manifest['requires_php'] ) ? $manifest['requires_php'] : '',
	);
}
add_filter( 'update_plugins_' . sppi_cfpb_update_host(), 'sppi_cfpb_check_update', 10, 3 );

/**
 * Fill in the "View details" modal, which core otherwise tries to fetch from
 * wordpress.org and cannot find.
 */
function sppi_cfpb_plugins_api( $result, $action, $args ) {
	if ( 'plugin_information' !== $action || empty( $args->slug ) || 'sppi-cfpb-dashboard' !== $args->slug ) {
		return $result;
	}

	$manifest = sppi_cfpb_get_manifest();
	if ( null === $manifest ) {
		return $result;
	}

	$info = array(
		'name'          => 'SPPI CFPB Complaint Dashboard',
		'slug'          => 'sppi-cfpb-dashboard',
		'version'       => $manifest['version'],
		'author'        => 'Southwest Public Policy Institute',
		'homepage'      => isset( $manifest['homepage'] ) ? $manifest['homepage'] : '',
		'download_link' => $manifest['download_url'],
		'requires'      => isset( $manifest['requires'] ) ? $manifest['requires'] : '',
		'requires_php'  => isset( $manifest['requires_php'] ) ? $manifest['requires_php'] : '',
		'tested'        => isset( $manifest['tested'] ) ? $manifest['tested'] : '',
		'last_updated'  => isset( $manifest['last_updated'] ) ? $manifest['last_updated'] : '',
		'sections'      => isset( $manifest['sections'] ) && is_array( $manifest['sections'] )
			? array_map( 'wp_kses_post', $manifest['sections'] )
			: array(),
	);

	return (object) $info;
}
add_filter( 'plugins_api', 'sppi_cfpb_plugins_api', 10, 3 );

/**
 * Drop the cached manifest whenever an administrator asks WordPress to check
 * for updates, so "Check again" on the Updates screen means it.
 */
function sppi_cfpb_force_update_recheck() {
	delete_transient( 'sppi_cfpb_update' );
}
add_action( 'load-update-core.php', 'sppi_cfpb_force_update_recheck' );
add_action( 'upgrader_process_complete', 'sppi_cfpb_force_update_recheck' );
