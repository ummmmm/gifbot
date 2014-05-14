import time
import json
import sys, traceback
from pprint import pprint
import praw
import re
import urlparse
import urllib2
import ConfigParser

class GIFBot:
	def __init__( self ):
		self._gif_cache				= {}
		self._commented_posts		= set()
		self._banned_subreddits		= set()
		self._blacklisted_domains	= ( 'reddit.com', 'wikipedia.org' )
		self._user_agent			= 'GIF_Link_Bot reddit bot by /u/ummmmm'
		self._browser_user_agent	= 'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/34.0.1847.131 Safari/537.36'
		self._imgur_pattern 		= re.compile( '/(\w{5,})' )
		self._href_pattern			= re.compile( '\[([^\[]+)\]\(([^\)]+)\)' )
		self._frames_pattern		= re.compile( '\x00\x21\xF9\x04' )
		self._r						= praw.Reddit( user_agent = self._user_agent )
		self._config				= Config()
		self._config_reddit			= self._config.section( 'Reddit' )
		self._config_imgur			= self._config.section( 'Imgur' )

		self._r.login( self._config_reddit[ 'username' ], self._config_reddit[ 'password' ] )

	def begin( self ):
		try:
			self._commented_posts 		= self.get_commented_submission_ids()
			self._banned_subreddits		= self.get_banned_subreddits()

			while True:
				all_comments 	= self._r.get_comments( 'all', limit = None )
				submission_ids 	= self.find_submission_ids( all_comments )
				self.check_submissions( submission_ids )
				time.sleep( 30 )
		except Exception as e:
			print 'Exception: ', e
			print traceback.format_exc()
			time.sleep( 300 )

	def build_comment( self, comments ):
		text = u''
		head = u'Here is a list of animated GIFs collected from the comments\n\n|Source Comment|Score|GIF Link|\n|:-------------|:----|:---------|\n'

		for comment in comments:
			for gif in comment[ 'gifs' ]:
				text += u'|[{author}]({permalink})|{score}|[{text}]({url})|\n'.format( author = comment[ 'author' ], permalink = comment[ 'permalink' ], score = comment[ 'score' ], url = gif[ 'url' ], text = gif[ 'text' ] )
			
		return head + text
			
	def post_comment( self, submission, comment ):
		attempts = 0

		while attempts < 5:
			attempts += 1

			try:
				submission.add_comment( comment )
				self._commented_posts.add( submission.id )
				return True
			except urllib2.HTTPError:
				self._banned_subreddits.add( submission.subreddit.display_name )
				print "Apparently I'm banned from this subreddit :("
				time.sleep( 5 )
			except Exception:
				print 'Apparently something went terrible wrong'
				return False
				time.sleep( 5 )

		return False

	def is_animated( self, url, domain, path ):
		if self._gif_cache.has_key( url ):
			return self._gif_cache[ url ]

		if domain.endswith( 'imgur.com' ) and self._config_imgur[ 'client_id' ]:
			self._gif_cache[ url ] = self.is_imgur_animated( path )
			return self._gif_cache[ url ]

		try:
			request 	= urllib2.Request( url, headers = { 'User-Agent:' : self._browser_user_agent } )
			response	= urllib2.urlopen( request, None, 10 )
					
			if response.info().getheader( 'Content-Type' ) == 'image/gif' and len( self._frames_pattern.findall( response.read() ) ) > 1:
				self._gif_cache[ url ] = True
			else:
				self._gif_cache[ url ] = False
		except Exception:
			return False

		return self._gif_cache[ url ]

	def is_imgur_animated( self, path ):
		name_object = self._imgur_pattern.match( path )

		if not name_object:
			return False

		try:
			request 	= urllib2.Request( 'https://api.imgur.com/3/image/{0}' . format( name_object.group( 1 ) ) )
			request.add_header( 'Authorization', 'Client-ID {0}' . format( self._config_imgur[ 'client_id' ] ) )
			response	= urllib2.urlopen( request, None, 10 )
			image		= json.loads( response.read() )

			if image[ 'success' ] and image[ 'data' ][ 'animated' ]:				
				return True
		except Exception:
			return False

		return False

	def find_gifs( self, body ):
		gifs = []

		for text, url in self._href_pattern.findall( body ):
			url 		= url.replace( '&amp;', '&' )
			parsed_url	= urlparse.urlparse( url )
			domain		= parsed_url.netloc.lower()
			path		= parsed_url.path

			if domain:
				if domain.endswith( ( self._blacklisted_domains ) ):
					continue

				if self.is_animated( url, domain, path ):
					gifs.append( { 'url': url, 'text': text } )

		return len( gifs ), gifs

	def find_submission_ids( self, comments ):
		submission_ids = set()

		for comment in comments:
			gifs_count, gifs = self.find_gifs( comment.body )

			if gifs_count:
				submission_ids.add( comment.submission.id )

		return submission_ids

	def get_commented_submission_ids( self ):
		commented_submission_ids = set()

		for comment in self._r.user.get_comments( time = 'all' ):
			commented_submission_ids.add( comment.link_id[ 3: ] )

		return commented_submission_ids

	def get_banned_subreddits( self ):
		banned_subreddits = set()

		for message in self._r.get_inbox():
			if message.subject == "you've been banned":
				banned_subreddits.add( message.subreddit.display_name )

		return banned_subreddits

	def check_submissions( self, submission_ids ):
		for submission_id in submission_ids:
			if	submission_id in self._commented_posts:
				print "[NO POST] Already commented on this submission"
				continue

			matches 	= []
			total		= 0
			submission 	= self._r.get_submission( submission_id = submission_id, comment_limit = None, comment_sort = 'top' )

			if submission.subreddit.display_name in self._banned_subreddits:
				print '[NO POST] Banned from subreddit "{0}"' . format( submission.subreddit.display_name )
				continue

			if submission.num_comments < int( self._config_reddit[ 'minimum_comments' ] ) or submission.num_comments > int( self._config_reddit[ 'maximum_comments' ] ):
				print '[NO POST] Submission has {0} comments' . format( submission.num_comments )
				continue

			submission.replace_more_comments( limit = None, threshold = 0 )

			for comment in praw.helpers.flatten_tree( submission.comments ):
				if comment.score < int( self._config_reddit[ 'minimum_comment_score' ] ):
					continue

				gifs_count, gifs = self.find_gifs( comment.body )

				if gifs_count:
					total += gifs_count
					matches.append( { 'gifs' : gifs, 'author': comment.author.name, 'permalink': comment.permalink, 'score': comment.score } )

			if total < int( self._config_reddit[ 'minimum_gifs' ] ):
				print "[NO POST] Submission has {0} animated GIFS" . format( total )
				continue

			matches = sorted( matches, key = lambda k: k[ 'score' ], reverse = True )
			comment	= self.build_comment( matches )

			if not self.post_comment( submission, comment ):
				continue

			print "[POST] Comment has been posted to submission id ", submission_id

class Config:
	def __init__( self ):
		self._config = ConfigParser.RawConfigParser()
		self._config.read( 'settings.ini' )

	def section( self, section ):
		dict = {}

		for option in self._config.options( section ):
			dict[ option ] = self._config.get( section, option )

		return dict