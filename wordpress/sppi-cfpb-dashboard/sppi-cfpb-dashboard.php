<?php
/**
 * Plugin Name:       SPPI CFPB Complaint Dashboard
 * Description:       Renders the Southwest Public Policy Institute's CFPB complaint-database dashboard from a published JSON feed. Use the [sppi_cfpb_dashboard] shortcode.
 * Version:           1.0.0
 * Requires at least: 6.0
 * Requires PHP:      7.4
 * Author:            Southwest Public Policy Institute
 * License:           GPL-2.0-or-later
 * Text Domain:       sppi-cfpb-dashboard
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'SPPI_CFPB_VERSION', '1.0.0' );
define( 'SPPI_CFPB_PATH', plugin_dir_path( __FILE__ ) );
define( 'SPPI_CFPB_URL', plugin_dir_url( __FILE__ ) );

/**
 * Default location of the published payload.
 *
 * Replace YOUR-GITHUB-ORG with the account or organisation that owns the
 * repository, or just set the real URL under Settings -> CFPB Dashboard.
 */
define( 'SPPI_CFPB_DEFAULT_FEED', 'https://YOUR-GITHUB-ORG.github.io/cfpb-complaint-dashboard/data/dashboard.json' );

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
 * Shortcode: [sppi_cfpb_dashboard panels="headline,trend,volume,states,companies,relief"]
 */
function sppi_cfpb_shortcode( $atts ) {
	$atts = shortcode_atts(
		array( 'panels' => 'headline,trend,volume,states,companies,relief' ),
		$atts,
		'sppi_cfpb_dashboard'
	);

	$result = sppi_cfpb_get_data();
	if ( null === $result['data'] ) {
		return '<div class="sppi-cfpb sppi-cfpb-error"><p>'
			. esc_html__( 'The complaint dashboard is temporarily unavailable.', 'sppi-cfpb-dashboard' )
			. '</p></div>';
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
				'data'   => $result['data'],
				'stale'  => (bool) $result['stale'],
				'panels' => $panels,
				// Served from the plugin's own directory, so the map geometry
				// is same-origin and needs no CORS headers from anywhere.
				'mapUrl' => SPPI_CFPB_URL . 'assets/us-states.json',
			)
		) . ';',
		'before'
	);

	$through = isset( $result['data']['meta']['data_through'] )
		? $result['data']['meta']['data_through'] : '';

	ob_start();
	?>
	<div class="sppi-cfpb" data-panels="<?php echo esc_attr( implode( ',', $panels ) ); ?>">
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

	$result = sppi_cfpb_get_data();
	$meta   = isset( $result['data']['meta'] ) ? $result['data']['meta'] : array();
	?>
	<div class="wrap">
		<h1><?php esc_html_e( 'CFPB Complaint Dashboard', 'sppi-cfpb-dashboard' ); ?></h1>

		<p><?php esc_html_e( 'Place the dashboard on any page or post with this shortcode:', 'sppi-cfpb-dashboard' ); ?>
			<code>[sppi_cfpb_dashboard]</code></p>
		<p><?php esc_html_e( 'To show only some panels:', 'sppi-cfpb-dashboard' ); ?>
			<code>[sppi_cfpb_dashboard panels="headline,trend"]</code></p>

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
	</div>
	<?php
}

/** Clear cached data on deactivation so a reinstall starts clean. */
function sppi_cfpb_deactivate() {
	delete_transient( 'sppi_cfpb_data' );
}
register_deactivation_hook( __FILE__, 'sppi_cfpb_deactivate' );
