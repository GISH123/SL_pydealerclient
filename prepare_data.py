import tensorflow as tf
import tensorflow_addons as tfa

# configuration.py
# Inception-v4 input
IMAGE_HEIGHT = 299
IMAGE_WIDTH  = 299
CHANNELS     = 3

AUTOTUNE = tf.data.AUTOTUNE

# Toggle stronger modern aug easily:
USE_TRIVIAL_AUG = False   # set False if you want ultra-fast, ultra-clean training
CUTOUT_PROB      = 0.25

def _letterbox_to_square(image, target_h=IMAGE_HEIGHT, target_w=IMAGE_WIDTH):
    h = tf.shape(image)[0]; w = tf.shape(image)[1]
    scale = tf.minimum(target_h / tf.cast(h, tf.float32),
                       target_w / tf.cast(w, tf.float32))
    nh = tf.cast(tf.round(tf.cast(h, tf.float32) * scale), tf.int32)
    nw = tf.cast(tf.round(tf.cast(w, tf.float32) * scale), tf.int32)
    image = tf.image.resize(image, [nh, nw], method=tf.image.ResizeMethod.BILINEAR)
    pad_h = target_h - nh; pad_w = target_w - nw
    pt = pad_h // 2; pb = pad_h - pt
    pl = pad_w // 2; pr = pad_w - pl
    image = tf.pad(image, [[pt, pb], [pl, pr], [0, 0]], mode='REFLECT')
    return tf.ensure_shape(image, [IMAGE_HEIGHT, IMAGE_WIDTH, CHANNELS])

def _cutout_edge(x):
    h = tf.shape(x)[0]; w = tf.shape(x)[1]
    ch = tf.random.uniform([], int(0.06*tf.cast(h,tf.float32)), int(0.12*tf.cast(h,tf.float32)), dtype=tf.int32)
    cw = tf.random.uniform([], int(0.06*tf.cast(w,tf.float32)), int(0.12*tf.cast(w,tf.float32)), dtype=tf.int32)
    edge = tf.random.uniform([]) < 0.7
    y = tf.where(edge, tf.random.uniform([], 0, ch//2+1, dtype=tf.int32),
                       tf.random.uniform([], 0, h-ch+1, dtype=tf.int32))
    x0 = tf.where(edge, tf.random.uniform([], 0, cw//2+1, dtype=tf.int32),
                        tf.random.uniform([], 0, w-cw+1, dtype=tf.int32))
    mask = tf.ones([ch, cw, CHANNELS], dtype=x.dtype)*0.5
    patch = tf.pad(mask, [[y, h-y-ch],[x0, w-x0-cw],[0,0]])
    return x * tf.cast(patch==0, x.dtype) + patch

def _trivial_augment(image):
    choice = tf.random.uniform([], 0, 6, dtype=tf.int32)
    magf = tf.random.uniform([], 0.5, 1.0)   # scale magnitude 50–100%
    def rot(img):  return tfa.image.rotate(img, 0.0349*magf)            # ~2 degrees
    def trot(img): return tfa.image.translate(img, [6.0*magf, 0.0])     # px shift
    def tcol(img): return tf.image.random_hue(img, 0.02*magf)
    def shearx(i): return tfa.image.transform(i, [1.0, 0.10*magf, 0, 0, 1.0, 0, 0, 0])
    def sheary(i): return tfa.image.transform(i, [1.0, 0, 0, 0.10*magf, 1.0, 0, 0, 0])
    def contrast(i): return tf.image.random_contrast(i, 0.9, 1.1)
    ops = [rot, trot, tcol, shearx, sheary, contrast]
    return tf.switch_case(choice, branch_fns=[lambda i=i: ops[i](image) for i in range(len(ops))])

def _augment(image):
    image = tf.image.random_brightness(image, max_delta=0.08)
    image = tf.image.random_contrast(image, lower=0.9, upper=1.1)
    if USE_TRIVIAL_AUG:
        image = _trivial_augment(image)
    if tf.random.uniform([]) < CUTOUT_PROB:
        image = _cutout_edge(image)
    return image

def load_and_preprocess_image(image_raw, data_augmentation=False):
    image = tf.io.decode_image(image_raw, channels=CHANNELS, dtype=tf.float32, expand_animations=False)
    image.set_shape([None, None, CHANNELS])
    image = _letterbox_to_square(image, IMAGE_HEIGHT, IMAGE_WIDTH)
    if data_augmentation:
        image = _augment(image)
    # Inception normalization [-1, 1]
    image = image * 2.0 - 1.0
    return image

def get_the_length_of_dataset(dataset):
    return sum(1 for _ in dataset)

# def generate_datasets():
#     train_dataset = get_parsed_dataset(train_tfrecord)
#     valid_dataset = get_parsed_dataset(valid_tfrecord)
#     test_dataset  = get_parsed_dataset(test_tfrecord)

#     # log counts (one pass each; small overhead once at start)
#     train_count = get_the_length_of_dataset(get_parsed_dataset(train_tfrecord))
#     valid_count = get_the_length_of_dataset(get_parsed_dataset(valid_tfrecord))
#     test_count  = get_the_length_of_dataset(get_parsed_dataset(test_tfrecord))
#     print(f"[Loader] train={train_count:,}  valid={valid_count:,}  test={test_count:,}  "
#           f"(batch={BATCH_SIZE}, trivial_aug={'on' if USE_TRIVIAL_AUG else 'off'})")

#     AUT = tf.data.AUTOTUNE
#     train_dataset = train_dataset.shuffle(8192).batch(BATCH_SIZE).prefetch(AUT)
#     valid_dataset = valid_dataset.batch(BATCH_SIZE).prefetch(AUT)
#     test_dataset  = test_dataset.batch(BATCH_SIZE).prefetch(AUT)
#     return train_dataset, valid_dataset, test_dataset, train_count, valid_count, test_count
