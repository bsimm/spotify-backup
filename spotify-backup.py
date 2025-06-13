#!/usr/bin/env python3

import argparse 
import codecs
import concurrent.futures
import http.client
import http.server
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Dict, List, Any, Optional

try:
	from rich.console import Console
	from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
	from rich.panel import Panel
	from rich.text import Text
	RICH_AVAILABLE = True
except ImportError:
	RICH_AVAILABLE = False
	print("Rich not available. Install with: pip install rich")
	print("Falling back to basic output...")

if RICH_AVAILABLE:
	console = Console()
else:
	console = None

logging.basicConfig(level=20, datefmt='%I:%M:%S', format='[%(asctime)s] %(message)s')

def log_message(message: str, style: str = None) -> None:
	"""Print message using rich console if available, otherwise use print"""
	if RICH_AVAILABLE and console:
		if style:
			console.print(message, style=style)
		else:
			console.print(message)
	else:
		print(message)


class SpotifyAPI:
	
	# Requires an OAuth token.
	def __init__(self, auth: str) -> None:
		self._auth = auth
	
	# Gets a resource from the Spotify API and returns the object.
	def get(self, url: str, params: Dict[str, Any] = {}, tries: int = 3) -> Dict[str, Any]:
		# Construct the correct URL.
		if not url.startswith('https://api.spotify.com/v1/'):
			url = 'https://api.spotify.com/v1/' + url
		if params:
			url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)
	
		# Try the sending off the request a specified number of times before giving up.
		for attempt in range(tries):
			try:
				req = urllib.request.Request(url)
				req.add_header('Authorization', 'Bearer ' + self._auth)
				res = urllib.request.urlopen(req)
				reader = codecs.getreader('utf-8')
				return json.load(reader(res))
			except urllib.error.HTTPError as err:
				if err.code == 401:
					log_message('Authentication failed. Check your OAuth token.', 'red bold')
					sys.exit(1)
				elif err.code == 429:
					log_message('Rate limited. Waiting longer before retry...', 'yellow')
					time.sleep(10 * (attempt + 1))
				else:
					log_message(f'HTTP error {err.code}: {err.reason} for URL: {url}', 'red')
					if attempt < tries - 1:
						time.sleep(2 * (attempt + 1))
			except urllib.error.URLError as err:
				log_message(f'Network error: {err.reason} for URL: {url}', 'red')
				if attempt < tries - 1:
					time.sleep(2 * (attempt + 1))
			except json.JSONDecodeError as err:
				log_message(f'Invalid JSON response from URL: {url} ({err})', 'red bold')
				if attempt < tries - 1:
					time.sleep(2)
			except Exception as err:
				log_message(f'Unexpected error: {err} for URL: {url}', 'red')
				if attempt < tries - 1:
					time.sleep(2)
			
			if attempt < tries - 1:
				log_message(f'Retrying... (attempt {attempt + 2}/{tries})', 'yellow')
		
		log_message(f'Failed to load URL after {tries} attempts: {url}', 'red bold')
		sys.exit(1)
	
	# The Spotify API breaks long lists into multiple pages. This method automatically
	# fetches all pages and joins them, returning in a single list of objects.
	def list(self, url: str, params: Dict[str, Any] = {}) -> List[Dict[str, Any]]:
		last_log_time = time.time()
		response = self.get(url, params)
		items = response['items']

		while response['next']:
			if time.time() > last_log_time + 15:
				last_log_time = time.time()
				log_message(f"Loaded {len(items)}/{response['total']} items", 'cyan')

			response = self.get(response['next'])
			items += response['items']
		return items
	
	# Pops open a browser window for a user to log in and authorize API access.
	@staticmethod
	def authorize(client_id: str, scope: str) -> 'SpotifyAPI':
		url = 'https://accounts.spotify.com/authorize?' + urllib.parse.urlencode({
			'response_type': 'token',
			'client_id': client_id,
			'scope': scope,
			'redirect_uri': 'http://127.0.0.1:{}/redirect'.format(SpotifyAPI._SERVER_PORT)
		})
		log_message(f'[bold blue]Logging in[/bold blue] (click if it doesn\'t open automatically):')
		log_message(f'[link]{url}[/link]', 'blue')
		webbrowser.open(url)
	
		# Start a simple, local HTTP server to listen for the authorization token... (i.e. a hack).
		server = SpotifyAPI._AuthorizationServer('127.0.0.1', SpotifyAPI._SERVER_PORT)
		try:
			while True:
				server.handle_request()
		except SpotifyAPI._Authorization as auth:
			return SpotifyAPI(auth.access_token)
		finally:
			server.server_close()
	
	# The port that the local server listens on. Don't change this,
	# as Spotify only will redirect to certain predefined URLs.
	_SERVER_PORT = 43019
	
	class _AuthorizationServer(http.server.HTTPServer):
		def __init__(self, host, port):
			http.server.HTTPServer.__init__(self, (host, port), SpotifyAPI._AuthorizationHandler)
		
		# Disable the default error handling.
		def handle_error(self, request, client_address):
			raise
	
	class _AuthorizationHandler(http.server.BaseHTTPRequestHandler):
		def do_GET(self):
			# The Spotify API has redirected here, but access_token is hidden in the URL fragment.
			# Read it using JavaScript and send it to /token as an actual query string...
			if self.path.startswith('/redirect'):
				self.send_response(200)
				self.send_header('Content-Type', 'text/html')
				self.end_headers()
				self.wfile.write(b'<script>location.replace("token?" + location.hash.slice(1));</script>')
			
			# Read access_token and use an exception to kill the server listening...
			elif self.path.startswith('/token?'):
				self.send_response(200)
				self.send_header('Content-Type', 'text/html')
				self.end_headers()
				self.wfile.write(b'<script>close()</script>Thanks! You may now close this window.')

				match = re.search('access_token=([^&]*)', self.path)
				if not match:
					self.send_error(400)
					return
				access_token = match.group(1)
				log_message('Received access token from Spotify', 'green')
				raise SpotifyAPI._Authorization(access_token)
			
			else:
				self.send_error(404)
		
		# Disable the default logging.
		def log_message(self, format, *args):
			pass
	
	class _Authorization(Exception):
		def __init__(self, access_token: str) -> None:
			self.access_token = access_token


def load_playlist_tracks(spotify: SpotifyAPI, playlist: Dict[str, Any]) -> Dict[str, Any]:
	"""Load tracks for a single playlist"""
	try:
		log_message(f"Loading playlist: [bold]{playlist['name']}[/bold] ({playlist['tracks']['total']} songs)", 'cyan')
		playlist['tracks'] = spotify.list(playlist['tracks']['href'], {'limit': 100})
		return playlist
	except Exception as e:
		log_message(f"Error loading playlist {playlist['name']}: {e}", 'red')
		return playlist


def get_top_items(spotify: SpotifyAPI, item_type: str, time_range: str, limit: int) -> List[Dict[str, Any]]:
	"""Get user's top artists or tracks"""
	try:
		log_message(f"Loading top {item_type} ({time_range}, limit={limit})...", 'cyan')
		items = spotify.list(f'me/top/{item_type}', {'time_range': time_range, 'limit': limit})
		log_message(f"Loaded [bold]{len(items)}[/bold] top {item_type}", 'green')
		return items
	except Exception as e:
		log_message(f"Error loading top {item_type}: {e}", 'red')
		return []


def main() -> None:
	# Show intro banner
	if RICH_AVAILABLE and console:
		console.print(Panel.fit(
			"[bold green]Spotify Backup Tool[/bold green]\n"
			"[dim]Export your playlists and liked songs[/dim]",
			border_style="green"
		))
	else:
		print("=== Spotify Backup Tool ===")
		print("Export your playlists and liked songs")
	
	# Parse arguments.
	parser = argparse.ArgumentParser(description='Exports your Spotify playlists. By default, opens a browser window '
	                                           + 'to authorize the Spotify Web API, but you can also manually specify'
	                                           + ' an OAuth token with the --token option.')
	parser.add_argument('--token', metavar='OAUTH_TOKEN', help='use a Spotify OAuth token (requires the '
	                                                         + '`playlist-read-private` permission)')
	parser.add_argument('--dump', default='playlists', 
	                    choices=['liked,playlists', 'playlists,liked', 'playlists', 'liked', 'top', 'top,playlists', 'playlists,top', 'top,liked', 'liked,top', 'top,playlists,liked', 'playlists,top,liked', 'liked,top,playlists'],
	                    help='dump playlists, liked songs, top items, or combinations (default: playlists)')
	parser.add_argument('--top-type', default='both', choices=['artists', 'tracks', 'both'],
	                    help='type of top items to fetch: artists, tracks, or both (default: both)')
	parser.add_argument('--time-range', default='medium_term', choices=['short_term', 'medium_term', 'long_term'],
	                    help='time range for top items: short_term (~4 weeks), medium_term (~6 months), long_term (~1 year) (default: medium_term)')
	parser.add_argument('--top-limit', type=int, default=50, metavar='N',
	                    help='number of top items to fetch (1-50, default: 50)')
	parser.add_argument('--format', default='txt', choices=['json', 'txt'], help='output format (default: txt)')
	parser.add_argument('file', help='output filename (optional, defaults to timestamped file)', nargs='?')
	args = parser.parse_args()
	
	# Generate automatic filename if none provided
	if not args.file:
		import datetime
		timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
		extension = 'json' if args.format == 'json' else 'txt'
		args.file = f'playlists-{timestamp}.{extension}'
		log_message(f'No filename provided, using: [bold]{args.file}[/bold]', 'cyan')
	else:
		# If user provided filename, check extension and update format accordingly
		file_ext = args.file.split('.')[-1].lower()
		if file_ext in ['json', 'txt']:
			args.format = file_ext
		else:
			log_message(f'Unknown file extension "{file_ext}", defaulting to txt format', 'yellow')
			args.format = 'txt'
	
	# Validate arguments
	if args.top_limit < 1 or args.top_limit > 50:
		log_message('Top limit must be between 1 and 50', 'red bold')
		sys.exit(1)
	
	# Validate OAuth token format if provided
	if args.token and (not args.token.strip() or len(args.token) < 50):
		log_message('Invalid OAuth token format. Token should be a long alphanumeric string.', 'red bold')
		sys.exit(1)
	
	# Determine required scopes based on what's being dumped
	scopes = []
	if any(x in args.dump for x in ['playlists', 'liked']):
		scopes.extend(['playlist-read-private', 'playlist-read-collaborative', 'user-library-read'])
	if 'top' in args.dump:
		scopes.append('user-top-read')
	
	# Log into the Spotify API.
	if args.token:
		spotify = SpotifyAPI(args.token)
	else:
		spotify = SpotifyAPI.authorize(client_id='5c098bcc800e45d49e476265bc9b6934',
		                               scope=' '.join(scopes))
	
	# Get the ID of the logged in user.
	log_message('Loading user info...', 'cyan')
	me = spotify.get('me')
	log_message(f"Logged in as [bold green]{me['display_name']}[/bold green] ([cyan]{me['id']}[/cyan])")

	playlists = []
	liked_albums = []
	top_artists = []
	top_tracks = []

	# List liked albums and songs
	if 'liked' in args.dump:
		log_message('Loading liked albums and songs...', 'cyan')
		liked_tracks = spotify.list('me/tracks', {'limit': 50})
		liked_albums = spotify.list('me/albums', {'limit': 50})
		playlists += [{'name': 'Liked Songs', 'tracks': liked_tracks}]

	# List all playlists and the tracks in each playlist
	if 'playlists' in args.dump:
		log_message('Loading playlists...', 'cyan')
		playlist_data = spotify.list('users/{user_id}/playlists'.format(user_id=me['id']), {'limit': 100})
		log_message(f'Found [bold]{len(playlist_data)}[/bold] playlists', 'green')
		
		if len(playlist_data) == 0:
			log_message('No playlists found for user', 'yellow')

		# Load all playlist tracks concurrently
		if RICH_AVAILABLE and console:
			with Progress(
				SpinnerColumn(),
				TextColumn("[progress.description]{task.description}"),
				BarColumn(),
				TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
				TimeElapsedColumn(),
				console=console
			) as progress:
				task = progress.add_task("Loading playlist tracks...", total=len(playlist_data))
				
				with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
					futures = [executor.submit(load_playlist_tracks, spotify, playlist) for playlist in playlist_data]
					for future in concurrent.futures.as_completed(futures):
						future.result()  # This will raise any exceptions
						progress.advance(task)
		else:
			# Fallback to sequential loading if rich not available
			for playlist in playlist_data:
				load_playlist_tracks(spotify, playlist)
		
		playlists += playlist_data
	
	# Get top items
	if 'top' in args.dump:
		if args.top_type in ['artists', 'both']:
			top_artists = get_top_items(spotify, 'artists', args.time_range, args.top_limit)
		if args.top_type in ['tracks', 'both']:
			top_tracks = get_top_items(spotify, 'tracks', args.time_range, args.top_limit)
	
	# Write the file.
	log_message('Writing files...', 'cyan')
	log_message(f'Playlists to write: {len(playlists)}', 'yellow')
	log_message(f'Liked albums to write: {len(liked_albums)}', 'yellow')
	log_message(f'Top artists to write: {len(top_artists)}', 'yellow')
	log_message(f'Top tracks to write: {len(top_tracks)}', 'yellow')
	
	with open(args.file, 'w', encoding='utf-8') as f:
		# JSON file.
		if args.format == 'json':
			data = {
				'playlists': playlists,
				'albums': liked_albums
			}
			if top_artists:
				data['top_artists'] = top_artists
			if top_tracks:
				data['top_tracks'] = top_tracks
			json.dump(data, f)
		
		# Tab-separated file.
		else:
			f.write('Playlists: \r\n\r\n')
			for playlist in playlists:
				f.write(playlist['name'] + '\r\n')
				for track in playlist['tracks']:
					if track['track'] is None:
						continue
					f.write('{name}\t{artists}\t{album}\t{uri}\t{release_date}\r\n'.format(
						uri=track['track']['uri'],
						name=track['track']['name'],
						artists=', '.join([artist['name'] for artist in track['track']['artists']]),
						album=track['track']['album']['name'],
						release_date=track['track']['album']['release_date']
					))
				f.write('\r\n')
			if len(liked_albums) > 0:
				f.write('Liked Albums: \r\n\r\n')
				for album in liked_albums:
					uri = album['album']['uri']
					name = album['album']['name']
					artists = ', '.join([artist['name'] for artist in album['album']['artists']])
					release_date = album['album']['release_date']
					album = f'{artists} - {name}'

					f.write(f'{name}\t{artists}\t-\t{uri}\t{release_date}\r\n')
				
				# Write top artists
				if len(top_artists) > 0:
					f.write(f'\r\nTop Artists ({args.time_range.replace("_", " ").title()}): \r\n\r\n')
					for i, artist in enumerate(top_artists, 1):
						name = artist['name']
						genres = ', '.join(artist['genres']) if artist['genres'] else 'No genres'
						followers = artist['followers']['total']
						uri = artist['uri']
						f.write(f'{i}\t{name}\t{genres}\t{followers} followers\t{uri}\r\n')
				
				# Write top tracks
				if len(top_tracks) > 0:
					f.write(f'\r\nTop Tracks ({args.time_range.replace("_", " ").title()}): \r\n\r\n')
					for i, track in enumerate(top_tracks, 1):
						name = track['name']
						artists = ', '.join([artist['name'] for artist in track['artists']])
						album = track['album']['name']
						uri = track['uri']
						release_date = track['album']['release_date']
						f.write(f'{i}\t{name}\t{artists}\t{album}\t{uri}\t{release_date}\r\n')

	log_message(f'[bold green]Successfully wrote file:[/bold green] [bold]{args.file}[/bold]')

if __name__ == '__main__':
	main()
