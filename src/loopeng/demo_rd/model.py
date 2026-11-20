"""Pure-Python deterministic binary classifier for the scientific-loop demo.

Toy synthetic data, not a published ML benchmark. Validation-only model selection;
held-out set is evaluated after search, never passed to the proposer.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
import math
import random


@dataclass(frozen=True)
class Config:
    feature_map: str
    lr: float
    l2: float
    epochs: int

    @classmethod
    def parse(cls, payload: dict) -> 'Config':
        if not isinstance(payload, dict) or set(payload) != {'feature_map','lr','l2','epochs'}:
            raise ValueError('Config requires exactly: feature_map, lr, l2, epochs')
        if payload['feature_map'] not in ('linear','interaction','quadratic'):
            raise ValueError('Feature map outside allowlist')
        if type(payload['epochs']) is not int or not 5 <= payload['epochs'] <= 500:
            raise ValueError('epochs must be in [5,500]')
        for key, lo, hi in [('lr',0.00001,0.5),('l2',0.0,2.0)]:
            if type(payload[key]) not in (int,float) or not math.isfinite(payload[key]) or not lo <= payload[key] <= hi:
                raise ValueError(f'{key} outside acceptable range')
        return cls(feature_map=payload['feature_map'], lr=float(payload['lr']),
                   l2=float(payload['l2']), epochs=payload['epochs'])


BASELINE = Config('linear', 0.05, 0.02, 120)
PREAUTHORED_HYPOTHESES = [
    Config('linear', 0.08, 0.001, 260),
    Config('interaction', 0.08, 0.01, 220),
    Config('linear', 0.0001, 1.0, 20),
    Config('quadratic', 0.07, 0.05, 240),
    Config('interaction', 0.12, 0.0, 300),
]


def make_dataset(seed: int=2026, n: int=720) -> dict:
    if n < 100 or n % 5 != 0:
        raise ValueError('n must be >=100 and divisible by 5')
    random_gen = random.Random(seed)
    by_class = {0:[], 1:[]}
    for _ in range(n):
        x0 = random_gen.uniform(-2,2)
        x1 = random_gen.uniform(-2,2)
        latent = x0*x1 + 0.40*x0 - 0.17*x1 + random_gen.gauss(0, 0.40)
        label = int(latent > 0)
        by_class[label].append(((x0,x1),label))
    partitions = {'train':[],'validation':[],'heldout':[]}
    for rows in by_class.values():
        random_gen.shuffle(rows)
        n_train = round(len(rows)*.60)
        n_val = round(len(rows)*.20)
        partitions['train'].extend(rows[:n_train])
        partitions['validation'].extend(rows[n_train:n_train+n_val])
        partitions['heldout'].extend(rows[n_train+n_val:])
    for rows in partitions.values():
        random_gen.shuffle(rows)
    raw = json.dumps({'seed':seed,'partitions':partitions},separators=(',',':')).encode()
    return {'seed':seed,'hash':hashlib.sha256(raw).hexdigest(), 'sets':partitions,
            'counts':{k:len(v) for k,v in partitions.items()}}


def features(x: tuple[float,float], name: str) -> list[float]:
    x0,x1 = x
    if name == 'linear':
        return [x0,x1]
    if name == 'interaction':
        return [x0,x1,x0*x1]
    if name == 'quadratic':
        return [x0,x1,x0*x1,x0*x0,x1*x1]
    raise ValueError('Unknown feature_map')


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    ez=math.exp(z)
    return ez/(1+ez)


def train(config: Config, training_rows: list) -> dict:
    X = [features(x,config.feature_map) for x,_ in training_rows]
    Y = [y for _,y in training_rows]
    dim = len(X[0])
    center = [sum(row[j] for row in X)/len(X) for j in range(dim)]
    std = [max(1e-8, math.sqrt(sum((row[j]-center[j])**2 for row in X)/len(X))) for j in range(dim)]
    normalized = [[(row[j]-center[j])/std[j] for j in range(dim)] for row in X]
    weights = [0.0]*(dim+1)
    for _ in range(config.epochs):
        gradients = [0.0]*(dim+1)
        for row,label in zip(normalized,Y):
            pred=sigmoid(weights[0]+sum(w*x for w,x in zip(weights[1:],row)))
            err=pred-label
            gradients[0]+=err
            for j,x in enumerate(row):
                gradients[j+1]+=err*x
        n = len(Y)
        weights[0] -= config.lr*gradients[0]/n
        for j in range(1,dim+1):
            weights[j] -= config.lr*(gradients[j]/n + config.l2*weights[j])
    return {'config':asdict(config),'weights':weights,'center':center,'std':std}


def classify(model: dict, x: tuple[float,float]) -> int:
    row=features(x,model['config']['feature_map'])
    normalized=[(v-u)/s for v,u,s in zip(row,model['center'],model['std'])]
    logits=model['weights'][0]+sum(w*v for w,v in zip(model['weights'][1:],normalized))
    return int(sigmoid(logits)>=0.5)


def evaluate(model: dict, rows: list) -> dict:
    y_true=[y for _,y in rows]
    y_pred=[classify(model,x) for x,_ in rows]
    tp=sum(a==1 and b==1 for a,b in zip(y_true,y_pred))
    fp=sum(a==0 and b==1 for a,b in zip(y_true,y_pred))
    fn=sum(a==1 and b==0 for a,b in zip(y_true,y_pred))
    tn=len(rows)-tp-fp-fn
    f1=2*tp/(2*tp+fp+fn) if (2*tp+fp+fn)>0 else 0.0
    return {'f1':round(f1,6),'accuracy':round((tp+tn)/len(rows),6),
            'n':len(rows),'tp':tp,'fp':fp,'fn':fn,'tn':tn}
