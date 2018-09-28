#!/usr/bin/python

# This is a dummy peer that just illustrates the available information your peers 
# have available.

# You'll want to copy this file to AgentNameXXX.py for various versions of XXX,
# probably get rid of the silly logging messages, and then add more logic.

import random
import logging

from messages import Upload, Request
from util import even_split
from peer import Peer

class chandStd(Peer):
    def post_init(self):
        print "post_init(): %s here!" % self.id
        self.std_state = dict()
        self.std_state["cycle"] = 0
        self.std_state["optimistic"] = None
    
    def requests(self, peers, history):
        """
        peers: available info about the peers (who has what pieces)
        history: what's happened so far as far as this peer can see

        returns: a list of Request() objects

        This will be called after update_pieces() with the most recent state.
        """
        needed = lambda i: self.pieces[i] < self.conf.blocks_per_piece
        needed_pieces = filter(needed, range(len(self.pieces)))
        np_set = set(needed_pieces)  # sets support fast intersection ops.

        # count number of each piece among peers
        piece_count = {}
        for p in peers:
            for piece in p.available_pieces:
                if piece in piece_count.keys():
                    piece_count[piece] = piece_count[piece] + 1
                else:
                    piece_count[piece] = 1


        logging.debug("%s here: still need pieces %s" % (
            self.id, needed_pieces))

        logging.debug("%s still here. Here are some peers:" % self.id)
        for p in peers:
            logging.debug("id: %s, available pieces: %s" % (p.id, p.available_pieces))

        logging.debug("And look, I have my entire history available too:")
        logging.debug("look at the AgentHistory class in history.py for details")
        logging.debug(str(history))

        requests = []   # We'll put all the things we want here
        # Symmetry breaking is good...
        random.shuffle(needed_pieces)
        
        # Sort peers by id.  This is probably not a useful sort, but other 
        # sorts might be useful
        peers.sort(key=lambda p: p.id)
        random.shuffle(peers)
        # request all available pieces from all peers!
        # (up to self.max_requests from each)
        for peer in peers:
            av_set = set(peer.available_pieces)
            isect = av_set.intersection(np_set)
            ###n = min(self.max_requests, len(isect))
            n = len(isect)
            available = list(isect)
            random.shuffle(available)
            available.sort(key=lambda p: piece_count[p])
            available2 = []
            inside = []
            i = 0
            if n > 0:
                v = piece_count[available[0]]
            while i < len(available):
                inside = []
                v = piece_count[available[i]]
                while i < len(available) and v == piece_count[available[i]]:
                    inside.append(available[i])
                    i += 1
                random.shuffle(inside)
                available2.append(inside)

            for s in available2:
                for piece_id in s:
                    start_block = self.pieces[piece_id]
                    r = Request(self.id, peer.id, piece_id, start_block)
                    requests.append(r)


     

        return requests

    def uploads(self, requests, peers, history):
        """
        requests -- a list of the requests for this peer for this round
        peers -- available info about all the peers
        history -- history for all previous rounds

        returns: list of Upload objects.

        In each round, this will be called after requests().
        """

        round = history.current_round()
        logging.debug("%s again.  It's round %d." % (
            self.id, round))
        # One could look at other stuff in the history too here.
        # For example, history.downloads[round-1] (if round != 0, of course)
        # has a list of Download objects for each Download to this peer in
        # the previous round.

        # if self.id == "chandStd0" and round>0:
        #     print history.uploads[round-1]

        if len(requests) == 0:
            logging.debug("No one wants my pieces!")
            chosen = []
            bws = []
        else:
            logging.debug("Still here: uploading to a random peer and up to top 3 from previous 2 rounds")
            

            # find the download bandwidth provided over the last two rounds by each peer requesting upload
            recent_downloads = {}
            for peer in peers:
                recent_downloads[peer.id] = 0

            if round >= 1:
                for d in history.downloads[round-1]:
                    recent_downloads[d.from_id] = recent_downloads[d.from_id] + d.blocks
            elif round >= 2:
                for d in history.downloads[round-2]:
                    recent_downloads[d.from_id] = recent_downloads[d.from_id] + d.blocks

            # sort requests by recent download bandwidth provided
            requests_by_peer = {}
            for r in requests:
                if r.requester_id in requests_by_peer.keys():
                    requests_by_peer[r.requester_id].append(r)
                else:
                    requests_by_peer[r.requester_id] = [r]

            requesters = requests_by_peer.keys()
            requesters.sort(key=lambda peer: -1*recent_downloads[peer])
            

            # choose up to top 3 requesters for unchoking
            chosen = []
            for i in range(min(3, len(requesters))):
                chosen.append(requesters[i])

            # continue to unchoke the optimistic unchoke selection for the 3 rounds, or select a new requester to optimistically unchoke
            if len(requesters) > 3:
                if self.std_state["cycle"] >= 2 or self.std_state["optimistic"] == None or self.std_state["optimistic"] not in requesters[:3]:
                    optimistic_unchoke = random.choice(requesters[3:])
                    self.std_state["cycle"] = 0
                    self.std_state["optimistic"] = optimistic_unchoke
                else:
                    optimistic_unchoke = self.std_state["optimistic"]
                    self.std_state["cycle"] += 1
                chosen.append(optimistic_unchoke)
            else:
                self.std_state["optimistic"] = None



            # Evenly "split" my upload bandwidth among the one chosen requester
            bws = even_split(self.up_bw, len(chosen))

        # create actual uploads out of the list of peer ids and bandwidths
        uploads = [Upload(self.id, peer_id, bw)
                   for (peer_id, bw) in zip(chosen, bws)]
            
        return uploads
