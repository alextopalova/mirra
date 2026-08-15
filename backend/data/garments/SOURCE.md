# Garment image provenance

The 70 garment photos in this directory (`<id>.jpg`) come from the Hugging
Face dataset **[yainage90/onthelook-fashion-anchor-positive-images](https://huggingface.co/datasets/yainage90/onthelook-fashion-anchor-positive-images)**,
a 166k-row image-retrieval training set of contemporary Korean fashion.

- **Dataset licence**: MIT, as declared on the dataset card by its
  publisher (Hugging Face user `yainage90`).
- **Product photography**: the images originate from **OnTheLook**
  (온더룩, [onthelook.co.kr](https://onthelook.co.kr)), a Korean fashion
  snap-and-shop app. Each dataset row pairs a street-snap crop
  (`anchor_image`) with the retailer's product shot for the same item
  (`positive_image`); we use only `positive_image` — the clean,
  mostly white-background shot the try-on endpoint sends YouCam as the
  garment reference. We downloaded, resized (long side capped at 1024px),
  and re-hosted a curated 70-item subset here rather than hot-linking any
  URL at runtime, so nothing in the demo depends on a third-party host.
  The MIT licence is the dataset publisher's declaration; the underlying
  photography is the retailer's and is identified as such here rather than
  claimed as original work.
- **How the subset was chosen and built**: see
  `backend/scripts/build_catalog.py`, which is runnable end-to-end and
  reproduces this directory and `backend/data/catalog.json` (network
  access required, no Hugging Face authentication needed). The 70 rows
  were **hand-picked by eye** from contact sheets of several hundred
  candidates — the dataset carries no product text at all, and its `top`
  and `bottom` classes skew heavily to men's streetwear, so selection had
  to filter for womenswear, for a usable single-garment photo (not a
  colourway collage, a rack of hangers, or a busy outdoor scene), and for
  a colour spread wide enough to keep all four personal-colour seasons
  populated. The script records each pick by its absolute dataset row
  index and re-downloads it through the public datasets-server `/rows`
  API. Names, silhouettes, prices, sizes and aisles in `catalog.json` are
  hand-authored there from looking at each photo; `color_hex` is sampled
  from the downloaded pixels and `color_lab` derived from it via the app's
  own `hex_to_lab`.
- **Scope of use**: images and metadata here are used only for a
  non-commercial hackathon prototype (an in-store styling kiosk demo).
  Prices in `catalog.json` are invented, plausible EUR high-street values;
  they are not the retailer's prices and no `buy_url` points anywhere.

## Previous source (superseded)

Until this revision the catalog used the Kaggle
[Fashion Product Images Dataset](https://www.kaggle.com/datasets/paramaggarwal/fashion-product-images-dataset)
(MIT metadata; photography from the Indian retailer Myntra). It was
replaced because the assortment looked dated and its prices were the
source dataset's Indian rupee values being rendered behind a "€" sign.
