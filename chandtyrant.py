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

class chandTyrant(Peer):
    def post_init(self):
        print "post_init(): %s here!" % self.id
        self.tyrant_state = dict()
        self.tyrant_state["cycle"] = 0
        self.gamma = 0.1
        self.alpha = 0.2
        self.r = 3
        self.f_ji = dict()
        self.tao = dict()
        self.unchoked = dict() # how many of the previous rounds have they unchoked me

    
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

        # at the beginning, initialize all Taos to 1/4 of bandwidth
        if round == 0:
            for p in peers:
                self.tao[p.id] = self.up_bw/4
                self.unchoked[p.id] = -1 # -1 signifies they have never unchoked me
            return []

        # did I upload to them or download from them in the last turn
        uploaded_to = dict()
        last_turn = dict()
        for p in peers:
            last_turn[p.id] = False
            uploaded_to[p.id] = False

        for u in history.uploads[round-1]:
            uploaded_to[u.to_id] = True

        # if I uploaded to them and they downloaded from me, set f_ji to the bandwidth they gave me
        # also track the number of turns they have unchoked me
        for download in history.downloads[round-1]:
            if uploaded_to[download.from_id]:
                if last_turn[download.from_id]:
                    self.f_ji[download.from_id] += download.blocks
                else:
                    self.f_ji[download.from_id] = download.blocks
                    last_turn[download.from_id] = True
                    if self.unchoked[download.from_id] < 1:
                        self.unchoked[download.from_id] = 1
                    else:
                        self.unchoked[download.from_id] += 1

        # for each peer I unchoked last turn, fine tune tao occording to procedure in the textbook
        for p in peers:
            if uploaded_to[p.id]:
                if not last_turn[p.id]:
                    self.tao[p.id] *= (1+self.alpha)
                    if self.unchoked[p.id] > 0:
                        self.unchoked[p.id] = 0
                elif self.unchoked[p.id] > self.r:
                    self.tao[p.id] *= (1-self.gamma)



        if len(requests) == 0:
            logging.debug("No one wants my pieces!")
            chosen = []
            bws = []

        else:
            logging.debug("Still here: uploading best ROI peers")
            # change my internal state for no reason
            for p in peers:
                if self.unchoked[p.id] == -1:
                    self.f_ji[p.id] = float(len(p.available_pieces) * self.conf.blocks_per_piece)/round

            # record how much each requester is requesting
            bw_requested = dict()
            blocks_per_piece = self.conf.blocks_per_piece
            for r in requests:
                if r.requester_id in bw_requested.keys():
                    bw_requested[r.requester_id] += (blocks_per_piece - r.start)
                else:
                    bw_requested[r.requester_id] = (blocks_per_piece - r.start)

            requesters = bw_requested.keys()
            # sort requesters by ROI in descending order
            requesters.sort(reverse=True, key=lambda r: self.f_ji[r]/self.tao[r])

            
            chosen = []
            bws = []

            # allocate all available bandwidth in order of descending ROI
            # allocate less than tao if they have requested less than tao
            # give remaining bandwidth to whoever is next in line
            remaining_bw = self.up_bw - 1 # had to make 1 less than total because it was giving an error otherwise
            j = 0
            while remaining_bw > 0 and j < len(requesters):
                to_allocate = min(self.tao[requesters[j]], bw_requested[requesters[j]], remaining_bw)
                chosen.append(requesters[j])
                bws.append(to_allocate)
                remaining_bw -= to_allocate
                j += 1


        # create actual uploads out of the list of peer ids and bandwidths
        uploads = [Upload(self.id, peer_id, bw)
                   for (peer_id, bw) in zip(chosen, bws)]
            
        return uploads









