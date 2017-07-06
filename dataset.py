""" Kaggle Sealion Pytorch Dataset
Pytorch Dataset code for patched based training and prediction of the
NOAA Fishes Sea Lion counting Kaggle data.

Dataset code generates or loads targets for density and counception
based counting models.
"""
from collections import defaultdict
import cv2
import torch
import torch.utils.data as data
from torch.utils.data.sampler import Sampler
from torchvision import datasets, transforms
from PIL import Image
import random
import pandas as pd
import numpy as np
import math
import os
import functools
import time
import mytransforms
import utils
import re

IMG_EXTENSIONS = ['.jpg', '.jpeg', '.png']
LABEL_TYPE = ['all', 'ground-cover', 'sky-cover', 'primary']

LABEL_ALL = [
    'blow_down',
    'conventional_mine',
    'slash_burn',
    'blooming',
    'artisinal_mine',
    'selective_logging',
    'bare_ground',
    'cloudy',
    'haze',
    'habitation',
    'cultivation',
    'partly_cloudy',
    'water',
    'road',
    'agriculture',
    'clear',
    'primary',
]

ALL_WEIGHTS = [
    382.7857142857,
    375.13,
    179.4880382775,
    112.9909638554,
    110.6578171091,
    110.3323529412,
    43.5185614849,
    17.9573958832,
    13.9091583241,
    10.2494535519,
    8.37904847,
    5.1663682688,
    5.061800027,
    4.6478751084,
    3.0461226147,
    1.3194400478,
    1.,
]

LABEL_GROUND_COVER = [
    'blow_down',
    'conventional_mine',
    'slash_burn',
    'blooming',
    'artisinal_mine',
    'selective_logging',
    'bare_ground',
    'habitation',
    'cultivation',
    'water',
    'road',
    'agriculture',
    'primary',
]

GROUND_COVER_WEIGHTS = [
    382.7857142857,
    375.13,
    179.4880382775,
    112.9909638554,
    110.6578171091,
    110.3323529412,
    43.5185614849,
    10.2494535519,
    8.37904847,
    5.061800027,
    4.6478751084,
    3.0461226147,
    1.,
]


LABEL_SKY_COVER = [
    'cloudy',
    'haze',
    'partly_cloudy',
    'clear',
]

SKY_COVER_WEIGHTS = [
    13.6098611776,
    3.4758257539,
    1.2910483485,
    1.
]

LABEL_PRIMARY = ['primary']


def get_tags(tags_type='all'):
    if tags_type == 'all':
        return LABEL_ALL
    elif tags_type == 'ground_cover':
        return LABEL_GROUND_COVER
    elif tags_type == 'sky_cover':
        return LABEL_SKY_COVER
    elif tags_type == 'primary':
        return LABEL_PRIMARY
    else:
        assert False and "Invalid label type"
        return []


def get_tags_size(tags_type='all'):
    return len(get_tags(tags_type))


def get_class_weights(tags_type='all'):
    if tags_type == 'all':
        return np.array(ALL_WEIGHTS)
    elif tags_type == 'ground_cover':
        return np.array(GROUND_COVER_WEIGHTS)
    elif tags_type == 'sky_cover':
        return np.array(SKY_COVER_WEIGHTS)
    else:
        return np.array([])


def find_inputs(folder, types=IMG_EXTENSIONS):
    inputs = []
    for root, _, files in os.walk(folder, topdown=False):
        for rel_filename in files:
            base, ext = os.path.splitext(rel_filename)
            if ext.lower() in types:
                abs_filename = os.path.join(root, rel_filename)
                inputs.append((base, abs_filename))
    return inputs


def natural_key(string_):
    """See http://www.codinghorror.com/blog/archives/001018.html"""
    return [int(s) if s.isdigit() else s for s in re.split(r'(\d+)', string_.lower())]


class AmazonDataset(data.Dataset):
    def __init__(
            self,
            input_root,
            target_file='',
            tags_type='all',
            multi_label=True,
            train=True,
            train_fold=False,
            fold=0,
            img_type='.jpg',
            img_size=(256, 256),
            transform=None):

        assert img_type in ['.jpg', '.tif']
        inputs = find_inputs(input_root, types=[img_type])
        if len(inputs) == 0:
            raise (RuntimeError("Found 0 images in : " + input_root))

        if target_file:
            target_df = pd.read_csv(target_file)
            if train or train_fold:
                target_df = target_df[target_df['fold'] != fold]
            else:
                target_df = target_df[target_df['fold'] == fold]
            target_df.drop(['fold'], 1, inplace=True)

            input_dict = dict(inputs)
            print(len(input_dict), len(target_df.index))
            target_df = target_df[target_df.image_name.map(lambda x: x in input_dict)]
            target_df['filename'] = target_df.image_name.map(lambda x: input_dict[x])
            self.inputs = target_df['filename'].tolist()
            print(len(self.inputs), len(target_df.index))

            tags = get_tags(tags_type)
            self.target_array = target_df.as_matrix(columns=tags).astype(np.float32)
            if not multi_label:
                self.target_array = np.argmax(self.target_array, axis=1)

            self.target_array = torch.from_numpy(self.target_array)
        else:
            assert not train
            inputs = sorted(inputs, key=lambda x: natural_key(x[0]))
            self.target_array = None
            self.inputs = [x[1] for x in inputs]

        self.tags_type = tags_type
        self.train = train
        if img_type == '.jpg':
            self.dataset_mean = [0.31535792, 0.34446435, 0.30275137]
            self.dataset_std = [0.05338271, 0.04247036, 0.03543708]
        else:
            #self.dataset_mean = [4988.75696302, 4270.74552695, 3074.87909779, 6398.84897763]
            #self.dataset_std = [399.06597519, 408.51461036, 453.1910904, 858.46477922]
            self.dataset_mean = [6398.84897763/2**16, 4988.75696302/2**16, 4270.74552695/2**16] # NRG
            self.dataset_std = [858.46477922/2**16, 399.06597519/2**16, 408.51461036/2**16] # NRG

        self.img_size = img_size
        self.img_type = img_type
        if transform is None:
            tfs = []
            if img_type == '.jpg':
                tfs.append(mytransforms.ToTensor())
                #if self.train:
                #    tfs.append(mytransforms.ColorJitter(brightness=0.1, contrast=0.1, saturation=0.1))
                tfs.append(transforms.Normalize(self.dataset_mean, self.dataset_std))
            else:
                #tfs.append(mytransforms.NormalizeImgIn64(self.dataset_mean, self.dataset_std))
                tfs.append(mytransforms.ToTensor())
                if self.train:
                    tfs.append(mytransforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.2))
                tfs.append(transforms.Normalize(self.dataset_mean, self.dataset_std))
            self.transform = transforms.Compose(tfs)

    def _load_input(self, index):
        path = self.inputs[index]
        #print("Loading %s" % path)
        if self.img_type == '.jpg':
            img = cv2.imread(path)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            return img
        else:
            img = cv2.imread(path, -1) # loaded as BGRN
            img_nrg = np.zeros((img.shape[0], img.shape[1], 3), dtype=img.dtype)
            img_nrg[:, :, 0] = img[:, :, 3]  # N
            img_nrg[:, :, 1] = img[:, :, 0]  # R
            img_nrg[:, :, 2] = img[:, :, 1]  # G
            return img_nrg

    def _random_crop_and_transform(self, input_img, rot=0.0):
        angle = 0.
        hflip = random.random() < 0.5
        vflip = random.random() < 0.5
        do_rotate = (rot > 0 and random.random() < 0.25) if not hflip and not vflip else False
        h, w = input_img.shape[:2]
        attempts = 0
        while attempts < 3:
            if do_rotate:
                angle = random.uniform(-rot, rot)
            scale = random.uniform(0.95, 1.05)
            crop_w, crop_h = utils.calc_crop_size(self.img_size[0], self.img_size[1], angle, scale)
            if crop_w <= w and crop_h <= h:
                break
            attempts += 1
        if crop_w > w or crop_h > h:
            #print('Crop %d, %d too large with rotation %f, skipping rotation.' % (crop_w, crop_h, angle))
            angle = 0.0
            crop_w, crop_h = utils.calc_crop_size(self.img_size[0], self.img_size[1], angle, scale)
        if crop_w > w or crop_h > h:
            #print('Crop %d, %d too large with scale %f, skipping scale.' % (crop_w, crop_h, angle))
            angle = 0.0
            scale = 1.0
            crop_w, crop_h = self.img_size[0], self.img_size[1]

        #print('hflip: %d, vflip: %d, angle: %f, scale: %f' % (hflip, vflip, angle, scale))
        hd = max(0, h - crop_h)
        wd = max(0, w - crop_w)
        ho = random.randint(0, hd) - math.ceil(hd / 2)
        wo = random.randint(0, wd) - math.ceil(wd / 2)
        cx = w // 2 + wo
        cy = h // 2 + ho
        #print(crop_w, crop_h, cx, cy, wd, hd, wo, ho)
        input_img = utils.crop_center(input_img, cx, cy, crop_w, crop_h)

        # Perform tile geometry transforms if needed
        if angle or hflip or vflip:
            Mtrans = np.identity(3)
            Mtrans[0, 2] = (self.img_size[0] - crop_w) // 2
            Mtrans[1, 2] = (self.img_size[1] - crop_h) // 2
            if hflip:
                Mtrans[0, 0] *= -1
                Mtrans[0, 2] = self.img_size[0] - Mtrans[0, 2] - 1
            if vflip:
                Mtrans[1, 1] *= -1
                Mtrans[1, 2] = self.img_size[1] - Mtrans[1, 2] - 1

            if angle or scale != 1.:
                Mrot = cv2.getRotationMatrix2D((crop_w//2, crop_h//2), angle, scale)
                Mfinal = np.dot(Mtrans, np.vstack([Mrot, [0, 0, 1]]))
            else:
                Mfinal = Mtrans

            input_img = cv2.warpAffine(input_img, Mfinal[:2, :], self.img_size, borderMode=cv2.BORDER_REFLECT_101)
        else:
            input_img = cv2.resize(input_img, self.img_size)

        return input_img

    def _centre_crop_and_scale(self, input_img, scale=1.0):
        h, w = input_img.shape[:2]
        cx = w // 2
        cy = h // 2
        crop_w, crop_h = utils.calc_crop_size(self.img_size[0], self.img_size[1], scale=scale)
        #print(crop_w, crop_h)
        input_img = utils.crop_center(input_img, cx, cy, crop_w, crop_h)
        if scale != 1.0:
            input_img = cv2.resize(input_img, self.img_size)
        #print(input_img.shape)
        return input_img

    def __getitem__(self, index):
        #input_path = self.inputs[index]
        input_img = self._load_input(index)
        if self.target_array is not None:
            target_tensor = self.target_array[index]
        else:
            target_tensor = torch.zeros(1)

        if self.train:
            input_img = self._random_crop_and_transform(input_img, rot=2.0)
            input_tensor = self.transform(input_img)
        else:
            input_img = self._centre_crop_and_scale(input_img, scale=1.0)
            input_tensor = self.transform(input_img)

        index_tensor = torch.LongTensor([index])
        #print(input_tensor.size(), target_tensor)

        return input_tensor, target_tensor, index_tensor

    def __len__(self):
        return len(self.inputs)

    def get_class_weights(self):
        return get_class_weights(self.tags_type)

