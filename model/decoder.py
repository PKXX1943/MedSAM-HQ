import math
import torch
from torch import nn, Tensor
from torch.nn import functional as F

from typing import List, Dict, Any, Tuple, Type, Optional

from .common import LayerNorm2d, LayerNorm1d, MLPBlock
from segment_anything.modeling.transformer import Attention, TwoWayTransformer
from segment_anything.modeling.mask_decoder import MaskDecoder
from segment_anything.modeling.prompt_encoder import PositionEmbeddingRandom
from .clip_encoder import ClipHead


# class ClipCellDecoder(nn.Module):
#     def __init__(
#         self, 
#         ClipCell_config: Dict[str, List],
#         input_dim: int,
#         output_dim: int,
#         vit_dim: int = 1024,
#         num_multimask_outputs: int = 3,
#         iou_head_depth: int = 3,
#         iou_head_hidden_dim: int = 256,
#         ):
#         super().__init__()
#         """
#         Predicts masks given an image embedding and correalative position embedding, patches clip features
#         and their position embeddings, and a text embedding. 
        
#         Args:
#           ClipCell_config: a dictionary of configurations for building decoder blocks. keys referrence below:
#                 input_dim (list[int]) : the channel dimension of the input embeddings of each block
#                 output_dim (list[int]) : the channel dimension of the output embeddings of each block
#                 transformer_depth (list[int]) : the number of transformer blocks in the transformer structure of each block
#                 downsample_rate (list[int]): downsample when doing qkv projection in attention blocks
#           input_dim : the channel dimension of the input embeddings of ClipCellDecoder
#           out_dim : the channel dimension of the final embeddings of of ClipCellDecoder
#           num_multimask_outputs : the number of masks to predict when disambiguating masks
#           iou_head_depth : the depth of the MLP used to predict mask quality
#           iou_head_hidden_dim : the hidden dimension of the MLP used to predict mask quality
#         """
#         self.blocks = nn.ModuleList([])
#         # self.compress_vit_feat = nn.ModuleList([])
#         # self.emebedding_encoder = nn.ModuleList([])
#         num_blocks = len(ClipCell_config["input_dim"])
#         # self.n_patches = ClipCell_config['n_patches']
#         for idx in range(num_blocks-1):
#             self.blocks.append(
#                 ClipCellBlock(
#                     # n_patches=self.n_patches,
#                     input_dim=ClipCell_config['input_dim'][idx],
#                     output_dim=ClipCell_config['output_dim'][idx],
#                     transformer_depth=ClipCell_config['transformer_depth'][idx],
#                     downsample_rate=ClipCell_config['downsample_rate'][idx]
#                 )
#             )
#         self.blocks.append(
#             ClipCellBlock(
#                     # n_patches=self.n_patches,
#                     input_dim=ClipCell_config['input_dim'][-1],
#                     output_dim=ClipCell_config['output_dim'][-1],
#                     transformer_depth=ClipCell_config['transformer_depth'][-1],
#                     downsample_rate=ClipCell_config['downsample_rate'][-1],
#                     last_block=True
#                 )
#         )
        
#         self.pe_layer = PositionEmbeddingRandom(input_dim//2)
        
#         self.num_multimask_outputs = num_multimask_outputs
#         self.iou_token = nn.Embedding(1, input_dim)
#         self.num_mask_tokens = num_multimask_outputs
#         self.mask_tokens = nn.Embedding(self.num_mask_tokens, input_dim)

#         self.iou_prediction_head = MLP(
#             output_dim, iou_head_hidden_dim, self.num_mask_tokens, iou_head_depth
#         )
#         self.compress_vit_feat = nn.Sequential(
#             nn.ConvTranspose2d(vit_dim, input_dim, kernel_size=2, stride=2),
#             LayerNorm2d(input_dim),
#             nn.GELU(), 
#             nn.ConvTranspose2d(input_dim, output_dim, kernel_size=2, stride=2)
#         )
        
#         self.embedding_encoder = nn.Sequential(
#             nn.ConvTranspose2d(input_dim, input_dim // 4, kernel_size=2, stride=2),
#             LayerNorm2d(input_dim // 4),
#             nn.GELU(), 
#             nn.ConvTranspose2d(input_dim // 4, output_dim, kernel_size=2, stride=2)
#         )

#         self.embedding_maskfeature = nn.Sequential(
#             nn.Conv2d(output_dim, output_dim * 2, 3, 1, 1), 
#             LayerNorm2d(output_dim * 2),
#             nn.GELU(),
#             nn.Conv2d(output_dim * 2, output_dim, 3, 1, 1)
#         )

#     def forward(
#         self,
#         n_patches: int,
#         image_embedding: Tensor,
#         vit_embedding: Tensor,
#         clip_embedding: Tensor,
#         clip_pe: Tensor,
#         text_embedding: Tensor,
#         similarity: Tensor = None,
#         multimask_output: bool = False,
#     ):
#         image_pe = self.pe_layer((image_embedding.size(2), image_embedding.size(3))).unsqueeze(0)
        
#         masks, iou_pred = self.predict_masks(
#             n_patches = n_patches,
#             image_embedding=image_embedding,
#             vit_embedding = vit_embedding,
#             image_pe=image_pe,
#             clip_embedding = clip_embedding,
#             clip_pe = clip_pe,
#             text_embedding = text_embedding,
#             similarity = similarity,
#         )

#         # Select the correct mask or masks for outptu
#         if multimask_output:
#             mask_slice = slice(1, None)
#         else:
#             mask_slice = slice(0, 1)
#         masks = masks[:, mask_slice, :, :]
#         iou_pred = iou_pred[:, mask_slice]

#         # Prepare output
#         return masks, iou_pred

#     def predict_masks(
#         self,
#         n_patches : int,
#         image_embedding: Tensor,
#         vit_embedding: Tensor,
#         image_pe: Tensor,
#         clip_embedding: Tensor,
#         clip_pe: Tensor,
#         text_embedding: Tensor,
#         similarity: Tensor = None,
#     ):
#         vit_features = vit_embedding[0].permute(0, 3, 1, 2) # early-layer ViT feature, after 1st global attention block in ViT
#         fusion_features = self.embedding_encoder(image_embedding) + self.compress_vit_feat(vit_features)

#         # Concatenate output tokens
#         output_tokens = torch.cat([self.iou_token.weight, self.mask_tokens.weight], dim=0)
#         output_tokens = output_tokens.unsqueeze(0).expand(text_embedding.size(0), -1, -1)
#         tokens = torch.cat((output_tokens, text_embedding), dim=1)

#         image_pe = torch.repeat_interleave(image_pe, tokens.shape[0], dim=0)
#         b, c, h, w = image_embedding.shape
        
#         for block in self.blocks:
#             image_embedding, image_pe, clip_embedding, clip_pe, tokens = \
#                 block(n_patches, image_embedding, image_pe, clip_embedding, clip_pe, tokens, similarity)
#         iou_token_out = tokens[:, 0, :]
#         mask_tokens_out = tokens[:, 1 : (1 + self.num_mask_tokens), :]
        
#         image_embedding = self.embedding_maskfeature(image_embedding) + fusion_features
        
#         b, c, h, w = image_embedding.shape
#         masks = (mask_tokens_out @ image_embedding.view(b, c, h * w)).view(b, -1, h, w)
        
#         # Generate mask quality predictions
#         iou_pred = self.iou_prediction_head(iou_token_out)

#         return masks, iou_pred
        
# class ClipCellBlock(nn.Module):
#     def __init__(
#         self, 
#         input_dim: int,
#         output_dim: int,
#         transformer_depth: int,
#         # n_patches: int,
#         downsample_rate: int,
#         attention_num_heads: int = 8,
#         mlp_ratio: int = 2,
#         activation: Type[nn.Module] = nn.GELU,
#         last_block: bool = False
#         ):
#         super().__init__()
#         self.pca = PatchCrossAttn(
#             # n_patches=n_patches,
#             embedding_dim=input_dim,
#             attention_num_heads=attention_num_heads,
#             downsample_rate=downsample_rate,
#             mlp_ratio=mlp_ratio,
#             activation=activation
#         )
        
#         self.transformer = TwoWayTransformer(
#             depth=transformer_depth,
#             embedding_dim=input_dim,
#             num_heads=attention_num_heads,
#             mlp_dim=input_dim * mlp_ratio,
#             activation=activation,
#             attention_downsample_rate=downsample_rate
#         )
        
#         self.upscaling = Upscaling(
#             input_dim=input_dim,
#             output_dim=output_dim,
#             activation=activation,
#             is_last=last_block     
#         )
    
#     def forward(
#         self,
#         n_patches: int,
#         image_embedding: Tensor,
#         image_pe: Tensor,
#         clip_embedding: Tensor,
#         clip_pe: Tensor,
#         tokens:Tensor,
#         similarity: Tensor = None
#     ):
#         b, c, h, w = image_embedding.shape
#         image_embedding = self.pca(n_patches, clip_embedding, image_embedding, clip_pe, image_pe, similarity)
#         tokens, image_embedding = self.transformer(image_embedding, image_pe, tokens)
#         return self.upscaling(image_embedding.transpose(1, 2).view(b, c, h, w), image_pe, clip_embedding, clip_pe, tokens)

class ClipCellDecoder(MaskDecoder):      
    def __init__(self, model_type):
        super().__init__(transformer_dim=256,
                        transformer=TwoWayTransformer(
                                depth=2,
                                embedding_dim=256,
                                mlp_dim=2048,
                                num_heads=8,
                            ),
                        num_multimask_outputs=3,
                        activation=nn.GELU,
                        iou_head_depth= 3,
                        iou_head_hidden_dim= 256,)
        transformer_dim = 256
        vit_dim_dict = {"vit_b":768,"vit_l":1024,"vit_h":1280}
        vit_dim = vit_dim_dict[model_type]
        self.clip_head = ClipHead(
            embedding_dim=512,
            transformer_dim=transformer_dim,
            vit_dim=vit_dim
        )
        self.pca = PatchCrossAttn(
            embedding_dim=vit_dim,
            attention_num_heads=8,
            downsample_rate=2
        )
        self.mlp = MLPBlock(transformer_dim, vit_dim*2)
        self.norm = LayerNorm2d(transformer_dim)
        self.pe_layer = PositionEmbeddingRandom(transformer_dim//2)

        self.vit_upscale = nn.Sequential(
                            nn.ConvTranspose2d(vit_dim, transformer_dim, kernel_size=2, stride=2),
                            LayerNorm2d(transformer_dim),
                            nn.GELU(), 
                            nn.ConvTranspose2d(transformer_dim, transformer_dim // 8, kernel_size=2, stride=2)
                        )
        
        self.embedding_upscale = nn.Sequential(
                            nn.ConvTranspose2d(transformer_dim, transformer_dim // 4, kernel_size=2, stride=2),
                            LayerNorm2d(transformer_dim // 4),
                            nn.GELU(),
                            nn.ConvTranspose2d(transformer_dim // 4, transformer_dim // 8, kernel_size=2, stride=2),
                        )

        self.adaptor = nn.Sequential(
                            nn.Conv2d(transformer_dim // 8, transformer_dim // 4, 3, 1, 1), 
                            LayerNorm2d(transformer_dim // 4),
                            nn.GELU(),
                            nn.Conv2d(transformer_dim // 4, transformer_dim // 8, 3, 1, 1)
                        )

    def forward(
        self,
        n_patches: int,
        image_embedding: Tensor,
        vit_embedding: Tensor,
        clip_embedding: Tensor,
        clip_img_token: Tensor,
        clip_text_token: Tensor,
        multimask_output: bool = False
    ):
        image_pe = self.pe_layer((image_embedding.size(2), image_embedding.size(3))).unsqueeze(0)
        clip_embedding, clip_img_token, clip_text_token, clip_pe = self.clip_head(
            n_patches, clip_embedding, clip_img_token, clip_text_token
        )
        masks, iou_pred = self.predict_masks(
            n_patches = n_patches,
            image_embedding=image_embedding,
            vit_embedding = vit_embedding,
            image_pe=image_pe,
            clip_embedding = clip_embedding,
            clip_pe = clip_pe,
            clip_img_token = clip_img_token,
            clip_text_token = clip_text_token,
        )
        # Select the correct mask or masks for outptu
        if multimask_output:
            mask_slice = slice(1, None)
        else:
            mask_slice = slice(0, 1)
        masks = masks[:, mask_slice, :, :]
        iou_pred = iou_pred[:, mask_slice]

        # Prepare output
        return masks, iou_pred

    def predict_masks(
        self,
        n_patches : int,
        image_embedding: Tensor,
        vit_embedding: Tensor,
        image_pe: Tensor,
        clip_embedding: Tensor,
        clip_pe: Tensor,
        clip_img_token : Tensor,
        clip_text_token : Tensor,
    ):
        vit_features = vit_embedding[0].permute(0, 3, 1, 2) # early-layer ViT feature, after 1st global attention block in ViT
        vit_features = self.pca(n_patches, clip_embedding, vit_features, clip_pe)
        fusion_feature = self.embedding_upscale(image_embedding) + self.vit_upscale(vit_features)

        # Concatenate output tokens
        output_tokens = torch.cat([self.iou_token.weight, self.mask_tokens.weight], dim=0)
        output_tokens = output_tokens.unsqueeze(0).expand(clip_text_token.size(0), -1, -1)
        tokens = torch.cat((output_tokens, clip_text_token), dim=1)

        pos_src = torch.repeat_interleave(image_pe, tokens.shape[0], dim=0)
        b, c, h, w = image_embedding.shape
        fused_tokens = self.mlp(image_embedding.permute(0,2,3,1).view(b, -1, c) + clip_img_token)
        src =  image_embedding.permute(0,2,3,1).view(b, -1, c) + fused_tokens
        src = self.norm(src.view(b, h, w, c).permute(0, 3, 1, 2))
        
        # Run the transformer
        hs, src = self.transformer(src, pos_src, tokens)
        iou_token_out = hs[:, 0, :]
        mask_tokens_out = hs[:, 1 : (1 + self.num_mask_tokens), :]

        # Upscale mask embeddings and predict masks using the mask tokens
        src = src.transpose(1, 2).view(b, c, h, w)
        upscaled_embedding = self.output_upscaling(src)
        upscaled_embedding_fusion = fusion_feature + self.adaptor(upscaled_embedding)
        hyper_in_list: List[torch.Tensor] = []
        for i in range(self.num_mask_tokens):
            hyper_in_list.append(self.output_hypernetworks_mlps[i](mask_tokens_out[:, i, :]))
        hyper_in = torch.stack(hyper_in_list, dim=1)
        b, c, h, w = upscaled_embedding_fusion.shape
        masks = (hyper_in @ upscaled_embedding_fusion.view(b, c, h * w)).view(b, -1, h, w)

        # Generate mask quality predictions
        iou_pred = self.iou_prediction_head(iou_token_out)

        return masks, iou_pred

        
class PatchCrossAttn(nn.Module):
    def __init__(
        self,
        # n_patches: int,
        embedding_dim: int,
        attention_num_heads: int,
        downsample_rate: int = 2,
        mlp_ratio: int = 2,
        activation: Type[nn.Module] = nn.SELU,
        ):
        super().__init__()
        # self.n_patches = n_patches
        # self.cross_attn_list = nn.ModuleList(
        #     [Attention(embedding_dim, attention_num_heads, downsample_rate) for i in range(n_patches*n_patches)]
        #     )
        self.cross_attn_patch = Attention(embedding_dim, attention_num_heads, downsample_rate)
        self.all_attn = Attention(embedding_dim, attention_num_heads, downsample_rate)
        self.norm0 = nn.LayerNorm(embedding_dim)
        self.norm1 = nn.LayerNorm(embedding_dim)
        self.norm2 = nn.LayerNorm(embedding_dim)
        self.mlp = MLPBlock(embedding_dim, embedding_dim*mlp_ratio)
        self.act = activation()
    
    def split_embed(self, image_embedding: Tensor , n_patches: int):
        bs, c, h, w = image_embedding.shape
        assert h % n_patches == 0 and w % n_patches == 0
        split_embedding = image_embedding.unfold(2, h // n_patches, h // n_patches).unfold(3, w // n_patches, w // n_patches)
        # (bs, c, n, n, h/n, w/n)
        split_embedding = split_embedding.permute(0, 2, 3, 1, 4, 5).contiguous()
        split_embedding = split_embedding.view(bs, n_patches * n_patches, c, h // n_patches, w // n_patches)
        
        return split_embedding
    
    def merge_embed(self, split_embedding: Tensor, n_patches: int):
        bs, _, c, h_s, w_s = split_embedding.shape
        combine_embedding = split_embedding.view(bs, n_patches, n_patches, c, h_s, w_s)

        combine_embedding = combine_embedding.permute(0, 3, 1, 4, 2, 5).contiguous()
        combine_embedding = combine_embedding.view(bs, c, h_s*n_patches, w_s*n_patches)
        
        return combine_embedding
        
    def forward(
        self,
        n_patches: int,
        clip_embedding: Tensor,
        image_embedding: Tensor,
        pos_embedding: Tensor,
    ):
        split_embedding = self.split_embed(image_embedding, n_patches)
        bs, _, c, h, w = split_embedding.shape
        pca_outs = []
        for patch_idx in range(n_patches * n_patches):
            split_patch = split_embedding[:, patch_idx, :, :, :]
            split_patch = (split_patch.permute(0,2,3,1)).view(bs, -1, c)
            attn_out = self.cross_attn_patch(
                q=split_patch,
                k=clip_embedding[:, patch_idx, :, :] + pos_embedding[:, [patch_idx], :],
                v=clip_embedding[:, patch_idx, :, :]
            )
            pca_outs.append((attn_out.view(bs, h, w, c)).permute(0, 3, 1, 2))
        pca_out = torch.stack(pca_outs, dim=1)
        split_embedding = split_embedding + pca_out

        out_embedding = self.merge_embed(split_embedding, n_patches)
        
        out_embedding = out_embedding.permute(0, 2, 3, 1).view(bs, -1, c)
        out_embedding = self.norm0(out_embedding)
        all_attn_out = self.all_attn(
            q=out_embedding,
            k=clip_embedding[:, -1, :, :],
            v=clip_embedding[:, -1, :, :]
        )
        
        out_embedding = self.norm1(out_embedding + all_attn_out)
        mlp_out = self.mlp(out_embedding)
        out_embedding = self.norm2(out_embedding + mlp_out)
        out_embedding = out_embedding.view(bs, h*n_patches, w*n_patches, c).permute(0, 3, 1, 2)
        
        return out_embedding
        
# class Upscaling(nn.Module):
#     def __init__(
#         self,
#         input_dim: int,
#         output_dim: int,
#         activation: Type[nn.Module] = nn.GELU,
#         is_last: bool = False
#         ):
#         super().__init__()
        
#         self.image_upscaling = nn.Sequential(
#             nn.ConvTranspose2d(input_dim*2, input_dim, kernel_size=2, stride=2),
#             LayerNorm2d(input_dim // 2),
#             activation(),
#             # MultiConvBlock(
#             #     input_dim//2, 
#             #     output_dim*2, 
#             #     activation, 
#             #     shortcut=nn.Conv2d(input_dim//2, output_dim*2, kernel_size=1, bias=False),
#             #     norm_output=not is_last
#             #     )
#             nn.ConvTranspose2d(input_dim, output_dim*2, kernel_size=2, stride=2),
#         )
        
#         self.clip_proj = nn.Linear(
#             input_dim,
#             output_dim,
#             bias=False
#         )
#         self.clip_norm = nn.LayerNorm(output_dim)
        
#         self.token_proj = MLP(
#             input_dim=input_dim,
#             hidden_dim=input_dim,
#             output_dim=output_dim,
#             num_layers=3,
#             norm_output=not is_last
#         )
    
#     def forward(
#         self,
#         image_embedding: Tensor,
#         image_pe: Tensor,
#         clip_embedding: Tensor,
#         clip_pe: Tensor,
#         tokens: Tensor,
#     ):
#         concat = torch.cat([image_embedding, image_pe], dim=1)
#         upscaled = self.image_upscaling(concat)
#         upscaled_image = upscaled[:, :upscaled.size(1)//2, :, :]
#         upscaled_pe = upscaled[:, upscaled.size(1)//2:, :, :]
        
#         num_embedding = clip_embedding.size(1)
#         clip_cat = torch.cat([clip_embedding, clip_pe], dim=1)
#         clip_p = self.clip_norm(self.clip_proj(clip_cat))
#         clip_out = clip_p[: , :num_embedding, :]
#         pe_out = clip_p[:, num_embedding:, :]
        
#         tokens_out = self.token_proj(tokens)
        
#         return upscaled_image, upscaled_pe, clip_out, pe_out, tokens_out
        
class ResBlock(nn.Module):
    def __init__(
        self, 
        in_channels: int, 
        out_channels: int, 
        activation: Type[nn.Module] = nn.GELU,
        shortcut: Optional[nn.Module] = None
        ):
        super(ResBlock, self).__init__()
        self.cnn = nn.Sequential(
            nn.Conv2d(in_channels, in_channels, kernel_size=3, stride=1, padding=1, bias=False),
            activation(),
            nn.Conv2d(in_channels, in_channels, kernel_size=3, stride=1, padding=1, bias=False),
            activation(),
            nn.Conv2d(in_channels, out_channels, kernel_size=1, bias=False),      
        )
        self.shortcut = shortcut
        self.norm = LayerNorm2d(out_channels)

    def forward(self, x: Tensor) -> Tensor:
        try:
            return self.norm(self.shortcut(x) + self.cnn(x))
        except:
            return self.norm(x + self.cnn(x))
    
# Lightly adapted from segment_anything/modeling/mask_decoder.py
class MLP(nn.Module):
    def __init__(
        self,
        input_dim: int,
        hidden_dim: int,
        output_dim: int,
        num_layers: int,
        norm_output: bool = True,
        sigmoid_output: bool = False,
    ):
        super().__init__()
        self.num_layers = num_layers
        h = [hidden_dim] * (num_layers - 1)
        self.layers = nn.ModuleList(
            nn.Linear(n, k) for n, k in zip([input_dim] + h, h + [output_dim])
        )
        self.sigmoid_output = sigmoid_output
        self.norm_output = norm_output
        if self.norm_output:
            self.norm = nn.LayerNorm(output_dim)

    def forward(self, x):
        for i, layer in enumerate(self.layers):
            x = F.relu(layer(x)) if i < self.num_layers - 1 else layer(x)
        if self.sigmoid_output:
            x = F.sigmoid(x)
        elif self.norm_output:
            x = self.norm(x)
        return x

class MultiConvBlock(nn.Module):
    def __init__(
        self, 
        in_channels: int, 
        out_channels: int, 
        activation: Type[nn.Module] = nn.GELU,
        shortcut: Optional[nn.Module] = None,
        norm_output: bool = True
        ):
        super().__init__()
        
        self.conv3 = nn.Conv2d(in_channels, in_channels, kernel_size=3, padding=1, bias=False)
        self.conv5 = nn.Conv2d(in_channels, in_channels, kernel_size=5, padding=2, bias=False)
        self.conv7 = nn.Conv2d(in_channels, in_channels, kernel_size=7, padding=3, bias=False)
        
        self.output = nn.Sequential(
            activation(),
            nn.Conv2d(in_channels, out_channels, kernel_size=1, bias=False)
        )
        
        self.shortcut = shortcut
        self.norm_output = norm_output
        if self.norm_output:
            self.norm = LayerNorm2d(out_channels)

    def forward(self, x):
        out3 = self.conv3(x)
        out5 = self.conv5(x)
        out7 = self.conv7(x)
        out = out3 + out5 + out7     
        if self.shortcut is not None:   
            out = self.shortcut(x) + self.output(out)
        else:
            out = x + self.output(out)
        if self.norm_output:
            return self.norm(out)
        else:
            return out