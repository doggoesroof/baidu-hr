# -*- coding: UTF-8 -*-
from __future__ import unicode_literals, print_function, division
from six import string_types, itervalues, iteritems
import six.moves.cPickle as pickle
from random import sample, choice, shuffle
from itertools import chain
from collections import defaultdict, Counter
from sklearn.cluster import KMeans
from .text import Corpus
from .skill import doc_tagger


def merge_weights(dict1, dict2, frac=0.67):
    if not dict2:
        return dict1
    else:
        dict1 = {k: dict1[k] * frac for k in dict1}
        dict2 = {k: dict2[k] * (1 - frac) for k in dict2}
        return dict(Counter(dict1) + Counter(dict2))


def _get_weight(post, resume):
    if hasattr(post, 'skills'):
        post_skills = post.skills
    else:
        post_skills = doc_tagger.tag(post.terms)
    if hasattr(resume, 'skills'):
        resume_skills = resume.skills
    else:
        resume_skills = doc_tagger.tag(resume.terms)

    # TODO: reduce weights after "优先"

    post_skills = list(chain(*post_skills))
    resume_skills = list(chain(*resume_skills))

    if resume_skills:
        rand_skill = choice(resume_skills)
    else:
        rand_skill = choice(post_skills)

    post_cnt = Counter(post_skills)
    reg_post = {k: v / sum(itervalues(post_cnt))
                for k, v in iteritems(post_cnt)}
    res_cnt = Counter(resume_skills)
    reg_res = {k: v / sum(itervalues(res_cnt))
               for k, v in iteritems(res_cnt)}

    weights = merge_weights(reg_post, reg_res)

    return weights, rand_skill


class QuestionBank:
    def __init__(self, mc_ques, sa_ques, model=None, keep_n=1000):
        sentences = [q.main + ';' + ','.join(q.options) for q in mc_ques]

        if model is None:
            # question clustering
            corpus = Corpus(sentences, keep_n=keep_n)
            model = KMeans(len(mc_ques) // 4, n_jobs=-1)
            model.fit(corpus.get_tfidf(sentences))
            labels = model.labels_
        else:
            if isinstance(model, string_types):
                corpus_state, model = pickle.load(open(model, 'rb'))
                corpus = Corpus.load_state(corpus_state)
            labels = model.predict(corpus.get_tfidf(sentences))

        self.corpus = corpus
        self.model = model

        for i, q in zip(labels, mc_ques):
            q.label = i

        mcq_dict = defaultdict(list)
        for ques in mc_ques:
            for skill in ques.skills:
                mcq_dict[skill].append(ques)

        self.mcq_clusters = dict()
        for skill in mcq_dict:
            ques_by_cluster = defaultdict(list)
            for q in mcq_dict[skill]:
                ques_by_cluster[q.label].append(q)
            mc_ques_clusters = list(itervalues(ques_by_cluster))
            self.mcq_clusters[skill] = mc_ques_clusters

        # build sa_dict in advance as it doesn't change
        self.sa_ques = sa_ques
        self.saq_dict = defaultdict(list)
        for ques in sa_ques:
            for skill in ques.skills:
                self.saq_dict[skill].append(ques)

    def save_model(self, filename):
        with open(filename, 'wb') as f:
            pickle.dump((self.corpus.get_state(), self.model), f, protocol=2)

    def recommend(self, post, resume, objnum=5, subjnum=1):
        weights, rand_skill = _get_weight(post, resume)

        ques_list = []

        c = min(itervalues(weights)) + 0.01
        counts = {k: int(round(v * objnum // c))
                  for k, v in iteritems(weights)}
        counts = sorted(iteritems(counts), key=lambda x: x[1], reverse=True)

        id_set = set()
        for k, v in counts:
            if v == 0 or k not in self.mcq_clusters:
                continue
            clusters = self.mcq_clusters[k]
            shuffle(clusters)
            cur_cluster = 0
            cnt = len([q for q in chain(*clusters) if q.id not in id_set])
            for i in range(min(v, cnt)):
                q = choice(clusters[cur_cluster])
                while q.id in id_set:
                    cur_cluster = (cur_cluster + 1) % len(clusters)
                    q = choice(clusters[cur_cluster])
                id_set.add(q.id)
                ques_list.append(q)

        ques_list = sample(ques_list, objnum)

        if rand_skill in self.saq_dict:
            subj = sample(self.saq_dict[rand_skill],
                          min(subjnum, len(self.saq_dict[rand_skill])))
        else:
            subj = []

        return ques_list, subj
