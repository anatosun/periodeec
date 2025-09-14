from setuptools import setup, find_packages

setup(
    name='periodeec',
    version='0.1.0',
    packages=find_packages(),
    description='Python cli utility to download your Spotify playlists.',
    author='Anatosun',
    author_email='z4jyol8l@duck.com',
    url='https://github.com/anatosun/periodeec',
    include_package_data=True,
    install_requires=[
        'requests',
        'spotipy',
        'spotipy-anon',
        'async-timeout',
        'beets>=2.4.0,<3.0.0',
        'deemix',
        'colorama',
        'schedule>=1.1.0',
        'plexapi>=4.7.0',
        'aiohttp>=3.8.0',
        'PyYAML>=6.0',
        'jsonschema>=4.0.0',
        'pathvalidate>=2.5.0',
    ],
    dependency_links=[
        'git+https://github.com/streetsamurai00mi/qz-dl.git#egg=qz-dl',
    ],
    entry_points={
        'console_scripts': [
            'periodeec = periodeec.main:main',
        ],
    },
)
