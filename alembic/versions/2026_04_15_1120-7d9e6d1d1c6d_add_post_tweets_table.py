"""add post_tweets table

Revision ID: 7d9e6d1d1c6d
Revises: c503b386ce5e
Create Date: 2026-04-15 11:20:00.000000

Adds a child table for persisted thread parts. Parent ``posts`` continues to
represent the publication-level lifecycle; ``post_tweets`` stores the ordered
text parts and the per-part X tweet ids once published.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d9e6d1d1c6d'
down_revision: Union[str, Sequence[str], None] = 'c503b386ce5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'post_tweets',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('post_id', sa.BigInteger(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('tweet_id', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('position >= 1', name='ck_post_tweets_position_positive'),
        sa.ForeignKeyConstraint(['post_id'], ['posts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_post_tweets_post_id', 'post_tweets', ['post_id'], unique=False)
    op.create_index('ix_post_tweets_tweet_id', 'post_tweets', ['tweet_id'], unique=False)
    op.create_index(
        'uq_post_tweets_post_id_position',
        'post_tweets',
        ['post_id', 'position'],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_post_tweets_post_id_position', table_name='post_tweets')
    op.drop_index('ix_post_tweets_tweet_id', table_name='post_tweets')
    op.drop_index('ix_post_tweets_post_id', table_name='post_tweets')
    op.drop_table('post_tweets')
